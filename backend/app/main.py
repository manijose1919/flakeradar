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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import github_integration, ingest, schemas
from .config import get_settings
from .db import get_db
from .migrate import run_migrations
from .models import TestCase, TestExecution, TestRun

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flakeradar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_migrations()
    if get_settings().api_token == "changeme":
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
        result = ingest.ingest_report(db, content, commit_sha, branch, ci_run_id)
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
def summary(db: Session = Depends(get_db)):
    s = get_settings()
    total_tests = db.scalar(select(func.count(TestCase.id))) or 0
    flaky = db.scalar(
        select(func.count(TestCase.id)).where(
            TestCase.flakiness_score >= s.flake_threshold
        )
    ) or 0
    confirmed = db.scalar(
        select(func.count(TestCase.id)).where(TestCase.confirmed_flake_count > 0)
    ) or 0
    runs = db.scalar(select(func.count(TestRun.id))) or 0
    execs = db.scalar(select(func.count(TestExecution.id))) or 0
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
):
    rows = (
        db.execute(
            select(TestCase)
            .where(TestCase.flakiness_score >= min_score)
            .order_by(TestCase.flakiness_score.desc(), TestCase.last_seen_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return rows


@app.get("/api/tests/{test_id}/history", response_model=schemas.HistoryOut)
def test_history(
    test_id: int,
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
):
    tc = db.get(TestCase, test_id)
    if tc is None:
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


# Serve the built frontend (frontend/dist) if present — single-container self-host.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
