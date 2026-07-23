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


def test_ingest_defaults_to_default_project(client):
    xml = make_junit([("t", "passed")])
    r = client.post("/api/ingest?commit_sha=s1", headers={"X-API-Key": "changeme"}, content=xml)
    assert r.status_code == 200
    assert r.json()["project"] == "default"


def test_tests_and_summary_filter_by_project(client):
    a = make_junit([("ta", "failed")])
    b = make_junit([("tb", "failed")])
    client.post("/api/ingest?commit_sha=s1&project=repo-a", headers={"X-API-Key": "changeme"}, content=a)
    client.post("/api/ingest?commit_sha=s1&project=repo-b", headers={"X-API-Key": "changeme"}, content=b)

    names = {t["name"] for t in client.get("/api/tests?project=repo-a").json()}
    assert names == {"ta"}
    assert client.get("/api/summary?project=repo-a").json()["total_tests"] == 1
    assert client.get("/api/summary").json()["total_tests"] == 2


def test_projects_endpoint_lists_distinct_projects(client):
    client.post("/api/ingest?commit_sha=s1&project=repo-a", headers={"X-API-Key": "changeme"}, content=make_junit([("t", "passed")]))
    client.post("/api/ingest?commit_sha=s1&project=repo-b", headers={"X-API-Key": "changeme"}, content=make_junit([("t", "passed")]))
    assert sorted(client.get("/api/projects").json()) == ["repo-a", "repo-b"]
