"""Same test name in two projects must be tracked as two independent cases."""
from app import ingest
from app.models import TestCase
from tests.conftest import make_junit


def test_same_name_different_projects_are_isolated(db_session):
    xml = make_junit([("test_login", "failed")])
    ingest.ingest_report(db_session, xml, "sha1", "main", "run1", "repo-a")
    ingest.ingest_report(db_session, xml, "sha1", "main", "run1", "repo-b")

    cases = db_session.query(TestCase).all()
    projects = sorted(c.project for c in cases)
    assert projects == ["repo-a", "repo-b"]
    assert len(cases) == 2


def test_same_project_same_name_reuses_case(db_session):
    xml = make_junit([("test_login", "failed")])
    ingest.ingest_report(db_session, xml, "sha1", "main", "run1", "repo-a")
    ingest.ingest_report(db_session, xml, "sha2", "main", "run2", "repo-a")

    assert db_session.query(TestCase).count() == 1
