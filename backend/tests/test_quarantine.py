"""Manual quarantine: open toggle, token-gated project-scoped list."""
from tests.conftest import make_junit

AUTH = {"X-API-Key": "changeme"}


def _ingest(client, name, project):
    client.post(
        f"/api/ingest?commit_sha=s1&project={project}",
        headers=AUTH, content=make_junit([(name, "failed")]),
    )


def _test_id(client, project):
    return client.get(f"/api/tests?project={project}").json()[0]["id"]


def test_toggle_quarantine_round_trip(client):
    _ingest(client, "t", "repo-a")
    tid = _test_id(client, "repo-a")

    on = client.post(f"/api/tests/{tid}/quarantine", json={"quarantined": True})
    assert on.status_code == 200
    body = on.json()
    assert body["quarantined"] is True
    assert body["quarantined_at"] is not None

    off = client.post(f"/api/tests/{tid}/quarantine", json={"quarantined": False})
    assert off.json()["quarantined"] is False
    assert off.json()["quarantined_at"] is None


def test_toggle_unknown_test_404(client):
    assert client.post("/api/tests/9999/quarantine", json={"quarantined": True}).status_code == 404


def test_quarantine_list_requires_token(client):
    assert client.get("/api/quarantine?project=repo-a").status_code == 401


def test_quarantine_list_is_project_scoped(client):
    _ingest(client, "ta", "repo-a")
    _ingest(client, "tb", "repo-b")
    a_id = _test_id(client, "repo-a")
    client.post(f"/api/tests/{a_id}/quarantine", json={"quarantined": True})

    listed = client.get("/api/quarantine?project=repo-a", headers=AUTH).json()
    assert [i["name"] for i in listed] == ["ta"]
    assert "fingerprint" in listed[0]
    assert client.get("/api/quarantine?project=repo-b", headers=AUTH).json() == []
