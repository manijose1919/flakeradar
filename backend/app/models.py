"""ORM models.

Design notes:
- A TestCase is identified by a stable fingerprint of (suite, classname, name),
  so the same logical test is tracked across runs, branches and CI providers.
- A TestRun represents one CI execution of the suite at a specific commit SHA.
  Executions are keyed by SHA (not just time) because a fail->pass flip on the
  SAME sha is proof of nondeterminism.
"""
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite's DATETIME discards tzinfo on write and returns naive datetimes
    on read; without this, serialized timestamps lack a UTC offset and
    browsers parse them as local time. Store normalized-naive UTC, re-attach
    tzinfo=UTC on load."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class TestCase(Base):
    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    suite: Mapped[str] = mapped_column(String(255), default="")
    classname: Mapped[str] = mapped_column(String(255), default="")
    name: Mapped[str] = mapped_column(String(500))

    # Cached analytics, recomputed on every ingest that touches this test.
    flakiness_score: Mapped[float] = mapped_column(Float, default=0.0)
    confirmed_flake_count: Mapped[int] = mapped_column(Integer, default=0)
    last_status: Mapped[str] = mapped_column(String(16), default="passed")
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # GitHub issue automation bookkeeping.
    github_issue_number: Mapped[int | None] = mapped_column(Integer, default=None)

    executions: Mapped[list["TestExecution"]] = relationship(
        back_populates="test_case", cascade="all, delete-orphan"
    )


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)
    branch: Mapped[str] = mapped_column(String(255), default="main")
    ci_run_id: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    executions: Mapped[list["TestExecution"]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )


class TestExecution(Base):
    __tablename__ = "test_executions"
    __table_args__ = (
        Index("ix_exec_case_time", "test_case_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), index=True)
    test_run_id: Mapped[int] = mapped_column(ForeignKey("test_runs.id"), index=True)

    status: Mapped[str] = mapped_column(String(16))  # passed | failed | error | skipped
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    test_case: Mapped[TestCase] = relationship(back_populates="executions")
    test_run: Mapped[TestRun] = relationship(back_populates="executions")
