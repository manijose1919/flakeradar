"""FastAPI application: ingest endpoint, read APIs, static frontend hosting."""
import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from . import github_integration, ingest, schemas
from .config import get_settings, assert_secure_token, DEFAULT_INSECURE_TOKEN
from .db import get_db
from .migrate import run_migrations
from .models import TestCase, TestExecution, TestRun, utcnow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flakeradar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    settings = get_settings()
    assert_secure_token(settings.api_token)
    if settings.api_token == DEFAULT_INSECURE_TOKEN:
        logger.warning(
            "FLAKERADAR_API_TOKEN is the default 'changeme' — set a real token."
        )
    yield


app = FastAPI(title="FlakeRadar", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_token(x_api_key: str = Header(default="")) -> None:
    expected = get_settings().api_token
    if not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/api/ingest",
    response_model=schemas.IngestOut,
    dependencies=[Depends(require_token)],
)
async def ingest_endpoint(
    request: Request,
    background: BackgroundTasks,
    commit_sha: str = Query(..., min_length=1, max_length=64),
    branch: str = Query(default="main", max_length=255),
    ci_run_id: str = Query(default="", max_length=255),
    project: str = Query(default="default", min_length=1, max_length=255),
    report: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
):
    """Accept a JUnit XML report as multipart upload (`report`) or raw body."""
    content = await report.read() if report is not None else await request.body()
    if not content:
        raise HTTPException(status_code=400, detail="Empty report body")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Report exceeds 20 MB limit")
    try:
        result = ingest.ingest_report(db, content, commit_sha, branch, ci_run_id, project)
    except ingest.IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if github_integration.configured():
        background.add_task(_file_issues_bg, result["touched_test_ids"])
    return result


def _file_issues_bg(test_case_ids: list[int]) -> None:
    from .db import SessionLocal  # fresh session: request session is closed by now

    db = SessionLocal()
    try:
        github_integration.file_issues_for(db, test_case_ids)
    finally:
        db.close()


@app.get("/api/summary", response_model=schemas.SummaryOut)
def summary(
    db: Session = Depends(get_db),
    project: str | None = Query(default=None),
):
    s = get_settings()

    def case_q(q):
        return q.where(TestCase.project == project) if project is not None else q

    total_tests = db.scalar(case_q(select(func.count(TestCase.id)))) or 0
    flaky = db.scalar(case_q(
        select(func.count(TestCase.id)).where(
            TestCase.flakiness_score >= s.flake_threshold
        )
    )) or 0
    confirmed = db.scalar(case_q(
        select(func.count(TestCase.id)).where(TestCase.confirmed_flake_count > 0)
    )) or 0
    runs_q = select(func.count(TestRun.id))
    if project is not None:
        runs_q = runs_q.where(TestRun.project == project)
    runs = db.scalar(runs_q) or 0
    execs_q = select(func.count(TestExecution.id))
    if project is not None:
        execs_q = execs_q.join(
            TestCase, TestExecution.test_case_id == TestCase.id
        ).where(TestCase.project == project)
    execs = db.scalar(execs_q) or 0
    return schemas.SummaryOut(
        total_tests=total_tests,
        flaky_tests=flaky,
        confirmed_flaky_tests=confirmed,
        total_runs=runs,
        total_executions=execs,
        flake_threshold=s.flake_threshold,
    )


@app.get("/api/tests", response_model=list[schemas.TestCaseOut])
def list_tests(
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
    min_score: float = Query(default=0.0, ge=0.0, le=1.0),
    project: str | None = Query(default=None),
):
    stmt = select(TestCase).where(TestCase.flakiness_score >= min_score)
    if project is not None:
        stmt = stmt.where(TestCase.project == project)
    rows = (
        db.execute(
            stmt.order_by(
                TestCase.flakiness_score.desc(), TestCase.last_seen_at.desc()
            ).limit(limit)
        )
        .scalars()
        .all()
    )
    return rows


@app.get("/api/projects", response_model=list[str])
def list_projects(db: Session = Depends(get_db)):
    return list(
        db.scalars(select(distinct(TestCase.project)).order_by(TestCase.project)).all()
    )


@app.get("/api/tests/{test_id}/history", response_model=schemas.HistoryOut)
def test_history(
    test_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    project: str | None = Query(default=None),
):
    tc = db.get(TestCase, test_id)
    if tc is None or (project is not None and tc.project != project):
        raise HTTPException(status_code=404, detail="Test not found")
    rows = db.execute(
        select(TestExecution, TestRun)
        .join(TestRun, TestExecution.test_run_id == TestRun.id)
        .where(TestExecution.test_case_id == test_id)
        .order_by(TestExecution.id.desc())
        .limit(limit)
    ).all()
    executions = [
        schemas.ExecutionOut(
            id=e.id,
            status=e.status,
            duration=e.duration,
            message=e.message,
            created_at=e.created_at,
            commit_sha=r.commit_sha,
            branch=r.branch,
            ci_run_id=r.ci_run_id,
        )
        for e, r in rows
    ]
    return schemas.HistoryOut(test=schemas.TestCaseOut.model_validate(tc), executions=executions)


@app.post("/api/tests/{test_id}/quarantine", response_model=schemas.TestCaseOut)
def set_quarantine(
    test_id: int,
    body: schemas.QuarantineIn,
    db: Session = Depends(get_db),
):
    tc = db.get(TestCase, test_id)
    if tc is None:
        raise HTTPException(status_code=404, detail="Test not found")
    tc.quarantined = body.quarantined
    tc.quarantined_at = utcnow() if body.quarantined else None
    db.commit()
    db.refresh(tc)
    return tc


@app.get(
    "/api/quarantine",
    response_model=list[schemas.QuarantineItem],
    dependencies=[Depends(require_token)],
)
def quarantine_list(
    db: Session = Depends(get_db),
    project: str = Query(default="default", min_length=1, max_length=255),
):
    rows = db.execute(
        select(TestCase)
        .where(TestCase.project == project, TestCase.quarantined.is_(True))
        .order_by(TestCase.name)
    ).scalars().all()
    return rows


# Serve the built frontend (frontend/dist) if present — single-container self-host.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
