"""Regression tests for the two code-review findings:
1. datetimes must serialize with a UTC offset (SQLite drops tzinfo),
2. concurrent first ingest of a new fingerprint must not 500 on the
   unique constraint.
"""
from app import ingest as ingest_mod
from app.ingest import ingest_report
from app.models import TestCase
from tests.conftest import TOKEN, make_junit

AUTH = {"X-API-Key": TOKEN}


def test_datetimes_serialize_with_utc_offset(client, db_session):
    client.post(
        "/api/ingest?commit_sha=abc",
        content=make_junit([("t1", "passed")]),
        headers=AUTH,
    )
    # Force attribute reload from SQLite so we exercise the read path that
    # production requests hit (fresh session -> naive datetime without fix).
    db_session.expire_all()
    row = client.get("/api/tests").json()[0]
    assert row["last_seen_at"].endswith(("+00:00", "Z")), row["last_seen_at"]

    hist = client.get(f"/api/tests/{row['id']}/history").json()
    assert hist["executions"][0]["created_at"].endswith(("+00:00", "Z"))


def test_concurrent_new_fingerprint_race_recovers(db_session, monkeypatch):
    real = ingest_mod._select_by_fingerprint
    state = {"first": True}

    def racy(db, fp):
        if state["first"]:
            state["first"] = False
            # Simulate a competing ingest committing the row between our
            # SELECT (which sees nothing) and our INSERT.
            db.add(TestCase(fingerprint=fp, suite="e2e", classname="c", name="t1"))
            db.flush()
            return None
        return real(db, fp)

    monkeypatch.setattr(ingest_mod, "_select_by_fingerprint", racy)
    result = ingest_report(db_session, make_junit([("t1", "passed")]), "sha", "main", "")
    assert result["ingested"] == 1

    # Exactly one TestCase row survived; the execution attached to it.
    rows = db_session.query(TestCase).all()
    assert len(rows) == 1
    assert len(rows[0].executions) == 1
