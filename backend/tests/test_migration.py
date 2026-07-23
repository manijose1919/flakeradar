"""Alembic migration behavior: fresh upgrade and pre-Alembic stamping."""
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _cfg(url: str) -> Config:
    cfg = Config("alembic.ini")          # cwd is backend/ under pytest
    cfg.set_main_option("script_location", "migrations")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_fresh_upgrade_to_baseline_creates_tables(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    command.upgrade(_cfg(url), "0001")
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"test_cases", "test_runs", "test_executions"} <= tables
