from tests.conftest import TOKEN, make_junit

AUTH = {"X-API-Key": TOKEN}


def _ingest(client, cases, sha, branch="main", run_id=""):
    return client.post(
        f"/api/ingest?commit_sha={sha}&branch={branch}&ci_run_id={run_id}",
        content=make_junit(cases),
        headers={**AUTH, "Content-Type": "application/xml"},
    )


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_ingest_requires_token(client):
    resp = client.post(
        "/api/ingest?commit_sha=abc", content=make_junit([("t1", "passed")])
    )
    assert resp.status_code == 401


def test_ingest_rejects_wrong_token(client):
    resp = client.post(
        "/api/ingest?commit_sha=abc",
        content=make_junit([("t1", "passed")]),
        headers={"X-API-Key": "wrong"},
    )
    assert resp.status_code == 401


def test_ingest_rejects_garbage(client):
    resp = client.post(
        "/api/ingest?commit_sha=abc", content=b"not xml at all", headers=AUTH
    )
    assert resp.status_code == 422


def test_ingest_rejects_empty_body(client):
    resp = client.post("/api/ingest?commit_sha=abc", headers=AUTH)
    assert resp.status_code == 400


def test_ingest_raw_body_roundtrip(client):
    resp = _ingest(client, [("t1", "passed"), ("t2", "failed")], sha="sha1")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ingested"] == 2
    assert data["counts"]["passed"] == 1
    assert data["counts"]["failed"] == 1


def test_ingest_multipart_upload(client):
    resp = client.post(
        "/api/ingest?commit_sha=sha1",
        files={"report": ("junit.xml", make_junit([("t1", "passed")]), "text/xml")},
        headers=AUTH,
    )
    assert resp.status_code == 200
    assert resp.json()["ingested"] == 1


def test_same_test_across_runs_is_one_test_case(client):
    _ingest(client, [("t1", "passed")], sha="sha1")
    _ingest(client, [("t1", "failed")], sha="sha2")
    tests = client.get("/api/tests").json()
    assert len(tests) == 1
    assert tests[0]["last_status"] == "failed"


def test_same_sha_retry_confirms_flake(client):
    # CI run fails, developer clicks re-run on the same commit, it passes.
    _ingest(client, [("t_flaky", "failed")], sha="deadbeef")
    _ingest(client, [("t_flaky", "passed")], sha="deadbeef")
    tests = client.get("/api/tests").json()
    assert tests[0]["confirmed_flake_count"] == 1
    assert tests[0]["flakiness_score"] >= 0.6


def test_stable_test_scores_zero(client):
    for i in range(5):
        _ingest(client, [("t_stable", "passed")], sha=f"sha{i}")
    tests = client.get("/api/tests").json()
    assert tests[0]["flakiness_score"] == 0.0


def test_leaderboard_orders_by_score(client):
    for i in range(6):
        status = "failed" if i % 2 else "passed"
        _ingest(client, [("t_flaky", status), ("t_stable", "passed")], sha=f"sha{i}")
    tests = client.get("/api/tests").json()
    assert tests[0]["name"] == "t_flaky"
    assert tests[0]["flakiness_score"] > tests[1]["flakiness_score"]


def test_min_score_filter(client):
    _ingest(client, [("t_stable", "passed")], sha="a")
    _ingest(client, [("t_stable", "passed")], sha="b")
    assert client.get("/api/tests?min_score=0.1").json() == []


def test_history_endpoint(client):
    _ingest(client, [("t1", "failed")], sha="sha1", branch="feat", run_id="42")
    _ingest(client, [("t1", "passed")], sha="sha1", branch="feat", run_id="43")
    test_id = client.get("/api/tests").json()[0]["id"]
    hist = client.get(f"/api/tests/{test_id}/history").json()
    assert hist["test"]["name"] == "t1"
    assert len(hist["executions"]) == 2
    # Newest first.
    assert hist["executions"][0]["status"] == "passed"
    assert hist["executions"][0]["ci_run_id"] == "43"
    assert hist["executions"][1]["commit_sha"] == "sha1"


def test_history_404(client):
    assert client.get("/api/tests/9999/history").status_code == 404


def test_summary(client):
    _ingest(client, [("t_flaky", "failed"), ("t_ok", "passed")], sha="s1")
    _ingest(client, [("t_flaky", "passed"), ("t_ok", "passed")], sha="s1")
    data = client.get("/api/summary").json()
    assert data["total_tests"] == 2
    assert data["total_runs"] == 2
    assert data["total_executions"] == 4
    assert data["confirmed_flaky_tests"] == 1
    assert data["flaky_tests"] == 1
