"""GitHub issue automation.

When a test's flakiness score crosses the configured threshold, file a
GitHub issue with the evidence. Runs as a FastAPI background task after
ingest, so a slow/unreachable GitHub API never delays a CI upload.

Behavior:
- No token or repo configured  -> silent no-op (self-host without GitHub).
- Issue already filed for test -> no-op (issue number stored on the row).
- API failure                  -> logged warning, never raised.
"""
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import TestCase, TestExecution, TestRun

logger = logging.getLogger("flakeradar.github")

LABEL = "flakeradar"
API_BASE = "https://api.github.com"


def configured() -> bool:
    s = get_settings()
    return bool(s.github_token and s.github_repo)


def _issue_body(db: Session, tc: TestCase) -> str:
    recent = db.execute(
        select(TestExecution, TestRun)
        .join(TestRun, TestExecution.test_run_id == TestRun.id)
        .where(TestExecution.test_case_id == tc.id)
        .order_by(TestExecution.id.desc())
        .limit(10)
    ).all()
    lines = [
        f"FlakeRadar detected a flaky test: `{tc.classname}::{tc.name}`",
        "",
        f"- **Flakiness score:** {tc.flakiness_score:.2f}",
        f"- **Same-commit fail/pass flips (proven nondeterminism):** {tc.confirmed_flake_count}",
        f"- **Suite:** {tc.suite or '(none)'}",
        "",
        "### Last 10 executions",
        "",
        "| Status | Commit | Branch | When (UTC) |",
        "|---|---|---|---|",
    ]
    sample_failure = ""
    for execution, run in recent:
        lines.append(
            f"| {execution.status} | `{run.commit_sha[:10]}` | {run.branch} "
            f"| {execution.created_at:%Y-%m-%d %H:%M} |"
        )
        if not sample_failure and execution.status in ("failed", "error"):
            sample_failure = execution.message
    if sample_failure:
        lines += ["", "### Sample failure message", "", "```", sample_failure[:1500], "```"]
    lines += ["", f"_Fingerprint: `{tc.fingerprint}`_"]
    return "\n".join(lines)


def file_issues_for(db: Session, test_case_ids: list[int]) -> None:
    """Create GitHub issues for newly-over-threshold tests. Never raises."""
    if not configured():
        return
    s = get_settings()
    candidates = (
        db.execute(
            select(TestCase).where(
                TestCase.id.in_(test_case_ids),
                TestCase.flakiness_score >= s.flake_threshold,
                TestCase.github_issue_number.is_(None),
            )
        )
        .scalars()
        .all()
    )
    if not candidates:
        return

    headers = {
        "Authorization": f"Bearer {s.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(base_url=API_BASE, headers=headers, timeout=15) as client:
            for tc in candidates:
                resp = client.post(
                    f"/repos/{s.github_repo}/issues",
                    json={
                        "title": f"[FlakeRadar] Flaky test: {tc.classname}::{tc.name}",
                        "body": _issue_body(db, tc),
                        "labels": [LABEL],
                    },
                )
                if resp.status_code == 201:
                    tc.github_issue_number = resp.json()["number"]
                    db.commit()
                    logger.info(
                        "Filed issue #%s for test %s", tc.github_issue_number, tc.id
                    )
                elif resp.status_code in (403, 429):
                    logger.warning(
                        "GitHub rate limit / forbidden (remaining=%s); stopping batch",
                        resp.headers.get("x-ratelimit-remaining"),
                    )
                    return
                else:
                    logger.warning(
                        "GitHub issue creation failed for test %s: %s %s",
                        tc.id, resp.status_code, resp.text[:300],
                    )
    except httpx.HTTPError as exc:
        logger.warning("GitHub unreachable, skipping issue filing: %s", exc)
