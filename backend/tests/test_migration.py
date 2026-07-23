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


def test_upgrade_0001_to_0002_adds_columns_and_backfills(tmp_path):
    url = f"sqlite:///{tmp_path / 'upgrade.db'}"
    cfg = _cfg(url)
    command.upgrade(cfg, "0001")

    eng = create_engine(url)
    with eng.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO test_cases "
            "(fingerprint, suite, classname, name, flakiness_score, "
            " confirmed_flake_count, last_status, last_seen_at) "
            "VALUES ('fp1','s','c','n',0.0,0,'passed','2026-01-01 00:00:00')"
        )

    command.upgrade(cfg, "0002")

    cols = {c["name"] for c in inspect(eng).get_columns("test_cases")}
    assert {"project", "quarantined", "quarantined_at"} <= cols
    assert "project" in {c["name"] for c in inspect(eng).get_columns("test_runs")}

    with eng.connect() as conn:
        project, quarantined = conn.exec_driver_sql(
            "SELECT project, quarantined FROM test_cases WHERE fingerprint='fp1'"
        ).first()
    assert project == "default"
    assert quarantined in (0, False)
