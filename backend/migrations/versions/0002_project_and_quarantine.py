"""project isolation + manual quarantine

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("test_cases", schema=None) as batch:
        batch.add_column(sa.Column("project", sa.String(length=255),
                                   nullable=False, server_default="default"))
        batch.add_column(sa.Column("quarantined", sa.Boolean(),
                                   nullable=False, server_default=sa.text("0")))
        batch.add_column(sa.Column("quarantined_at", sa.DateTime(), nullable=True))
        batch.drop_index("ix_test_cases_fingerprint")
        batch.create_index("ix_test_cases_fingerprint", ["fingerprint"], unique=False)
        batch.create_index("ix_test_cases_project", ["project"])
        batch.create_unique_constraint(
            "uq_test_cases_project_fingerprint", ["project", "fingerprint"]
        )

    with op.batch_alter_table("test_runs", schema=None) as batch:
        batch.add_column(sa.Column("project", sa.String(length=255),
                                   nullable=False, server_default="default"))


def downgrade() -> None:
    with op.batch_alter_table("test_runs", schema=None) as batch:
        batch.drop_column("project")
    with op.batch_alter_table("test_cases", schema=None) as batch:
        batch.drop_constraint("uq_test_cases_project_fingerprint", type_="unique")
        batch.drop_index("ix_test_cases_project")
        batch.drop_index("ix_test_cases_fingerprint")
        batch.create_index("ix_test_cases_fingerprint", ["fingerprint"], unique=True)
        batch.drop_column("quarantined_at")
        batch.drop_column("quarantined")
        batch.drop_column("project")
