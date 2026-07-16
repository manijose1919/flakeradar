"""JUnit XML ingestion: parse, fingerprint, persist, rescore."""
import hashlib
from dataclasses import dataclass

from junitparser import Error, Failure, JUnitXml, Skipped, TestSuite
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import scoring
from .config import get_settings
from .models import TestCase, TestExecution, TestRun, utcnow


class IngestError(ValueError):
    """Raised when the uploaded report cannot be parsed."""


@dataclass
class ParsedCase:
    suite: str
    classname: str
    name: str
    status: str
    duration: float
    message: str


def fingerprint(suite: str, classname: str, name: str) -> str:
    raw = f"{suite}::{classname}::{name}".encode()
    return hashlib.sha1(raw).hexdigest()


def _case_status(case) -> tuple[str, str]:
    """Map junitparser results to (status, message)."""
    for result in case.result:
        text = (result.message or "") if hasattr(result, "message") else ""
        if isinstance(result, Failure):
            return "failed", text
        if isinstance(result, Error):
            return "error", text
        if isinstance(result, Skipped):
            return "skipped", text
    return "passed", ""


def parse_junit_xml(content: bytes) -> list[ParsedCase]:
    try:
        xml = JUnitXml.fromstring(content.decode("utf-8", errors="replace"))
    except Exception as exc:  # junitparser raises lxml/xml parse errors
        raise IngestError(f"Not a valid JUnit XML report: {exc}") from exc

    # A file may be a <testsuites> wrapper or a single bare <testsuite>.
    suites = list(xml) if isinstance(xml, JUnitXml) else [xml]
    parsed: list[ParsedCase] = []
    for suite in suites:
        if not isinstance(suite, TestSuite):
            continue
        for case in suite:
            if case.name is None:
                continue
            status, message = _case_status(case)
            parsed.append(
                ParsedCase(
                    suite=suite.name or "",
                    classname=case.classname or "",
                    name=case.name,
                    status=status,
                    duration=float(case.time or 0.0),
                    message=message[:2000],
                )
            )
    if not parsed:
        raise IngestError("Report parsed but contained no test cases.")
    return parsed


def _select_by_fingerprint(db: Session, fp: str) -> TestCase | None:
    return db.execute(
        select(TestCase).where(TestCase.fingerprint == fp)
    ).scalar_one_or_none()


def _get_or_create_case(db: Session, pc: ParsedCase, fp: str) -> TestCase:
    """Get-or-create guarded against the concurrent-first-ingest race:
    two CI jobs reporting a brand-new test at the same time both SELECT
    nothing, then one INSERT loses on the unique fingerprint constraint.
    A savepoint confines the rollback to just that insert."""
    tc = _select_by_fingerprint(db, fp)
    if tc is not None:
        return tc
    try:
        with db.begin_nested():
            tc = TestCase(
                fingerprint=fp, suite=pc.suite, classname=pc.classname, name=pc.name
            )
            db.add(tc)
    except IntegrityError:
        tc = _select_by_fingerprint(db, fp)
        if tc is None:  # constraint violation was something else entirely
            raise
    return tc


def rescore(db: Session, test_case: TestCase) -> None:
    settings = get_settings()
    rows = db.execute(
        select(TestExecution.status, TestRun.commit_sha)
        .join(TestRun, TestExecution.test_run_id == TestRun.id)
        .where(TestExecution.test_case_id == test_case.id)
        .order_by(TestExecution.id.desc())
        .limit(settings.score_window)
    ).all()
    statuses = [r.status for r in rows]
    with_sha = [(r.commit_sha, r.status) for r in rows]
    score, confirmed = scoring.combined_score(
        statuses, with_sha, settings.score_decay, settings.score_window
    )
    test_case.flakiness_score = score
    test_case.confirmed_flake_count = confirmed


def ingest_report(
    db: Session, content: bytes, commit_sha: str, branch: str, ci_run_id: str
) -> dict:
    """Persist one JUnit report. Returns a summary dict for the API response."""
    parsed = parse_junit_xml(content)

    run = TestRun(commit_sha=commit_sha, branch=branch, ci_run_id=ci_run_id)
    db.add(run)
    db.flush()

    touched: dict[int, TestCase] = {}
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0}
    for pc in parsed:
        fp = fingerprint(pc.suite, pc.classname, pc.name)
        tc = _get_or_create_case(db, pc, fp)
        tc.last_status = pc.status
        tc.last_seen_at = utcnow()
        db.add(
            TestExecution(
                test_case_id=tc.id,
                test_run_id=run.id,
                status=pc.status,
                duration=pc.duration,
                message=pc.message,
            )
        )
        counts[pc.status] += 1
        touched[tc.id] = tc

    db.flush()
    for tc in touched.values():
        rescore(db, tc)
    db.commit()

    return {
        "run_id": run.id,
        "commit_sha": commit_sha,
        "branch": branch,
        "ingested": len(parsed),
        "counts": counts,
        "touched_test_ids": sorted(touched),
    }
