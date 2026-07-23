"""Pydantic response models — the typed contract the frontend consumes."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class TestCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fingerprint: str
    project: str
    suite: str
    classname: str
    name: str
    flakiness_score: float
    confirmed_flake_count: int
    last_status: str
    last_seen_at: datetime
    quarantined: bool
    quarantined_at: datetime | None
    github_issue_number: int | None


class ExecutionOut(BaseModel):
    id: int
    status: str
    duration: float
    message: str
    created_at: datetime
    commit_sha: str
    branch: str
    ci_run_id: str


class HistoryOut(BaseModel):
    test: TestCaseOut
    executions: list[ExecutionOut]


class SummaryOut(BaseModel):
    total_tests: int
    flaky_tests: int
    confirmed_flaky_tests: int
    total_runs: int
    total_executions: int
    flake_threshold: float


class IngestOut(BaseModel):
    run_id: int
    commit_sha: str
    branch: str
    project: str
    ingested: int
    counts: dict[str, int]
    touched_test_ids: list[int]
