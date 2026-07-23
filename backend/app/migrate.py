"""Run Alembic migrations at startup, tolerant of pre-Alembic databases.

A database created by the old `Base.metadata.create_all` path has the app
tables but no `alembic_version` marker. Running `upgrade` on it directly would
try to re-create existing tables and fail, so we stamp it at baseline first.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import engine

_BASELINE_REVISION = "0001"


def _alembic_config() -> Config:
    backend_root = Path(__file__).resolve().parents[1]  # backend/
    cfg = Config(str(backend_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    return cfg


def run_migrations() -> None:
    tables = set(inspect(engine).get_table_names())
    cfg = _alembic_config()
    if "test_cases" in tables and "alembic_version" not in tables:
        command.stamp(cfg, _BASELINE_REVISION)
    command.upgrade(cfg, "head")
