"""baseline schema (pre-v1.1)

Revision ID: 0001
Revises:
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(length=40), nullable=False),
        sa.Column("suite", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("classname", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("flakiness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("confirmed_flake_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_status", sa.String(length=16), nullable=False, server_default="passed"),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("github_issue_number", sa.Integer(), nullable=True),
    )
    op.create_index("ix_test_cases_fingerprint", "test_cases", ["fingerprint"], unique=True)

    op.create_table(
        "test_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False, server_default="main"),
        sa.Column("ci_run_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_test_runs_commit_sha", "test_runs", ["commit_sha"])

    op.create_table(
        "test_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_cases.id"), nullable=False),
        sa.Column("test_run_id", sa.Integer(), sa.ForeignKey("test_runs.id"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_test_executions_test_case_id", "test_executions", ["test_case_id"])
    op.create_index("ix_test_executions_test_run_id", "test_executions", ["test_run_id"])
    op.create_index("ix_exec_case_time", "test_executions", ["test_case_id", "id"])


def downgrade() -> None:
    op.drop_table("test_executions")
    op.drop_table("test_runs")
    op.drop_table("test_cases")
