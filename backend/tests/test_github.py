from unittest.mock import MagicMock, patch

from app import github_integration
from app.config import Settings
from app.ingest import ingest_report
from tests.conftest import make_junit


def _make_flaky_test(db):
    """Ingest a fail + pass on the same SHA -> confirmed flake over threshold."""
    ingest_report(db, make_junit([("t_flaky", "failed")]), "sha1", "main", "")
    result = ingest_report(db, make_junit([("t_flaky", "passed")]), "sha1", "main", "")
    return result["touched_test_ids"]


def _configure(monkeypatch, **overrides):
    settings = Settings(github_token="tok", github_repo="acme/app", **overrides)
    monkeypatch.setattr("app.github_integration.get_settings", lambda: settings)
    return settings


def test_unconfigured_is_noop(db_session):
    ids = _make_flaky_test(db_session)
    assert not github_integration.configured()
    with patch("app.github_integration.httpx.Client") as client_cls:
        github_integration.file_issues_for(db_session, ids)
    client_cls.assert_not_called()


def test_files_issue_and_stores_number(db_session, monkeypatch):
    ids = _make_flaky_test(db_session)
    _configure(monkeypatch)

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    resp = MagicMock(status_code=201)
    resp.json.return_value = {"number": 77}
    mock_client.post.return_value = resp

    with patch("app.github_integration.httpx.Client", return_value=mock_client):
        github_integration.file_issues_for(db_session, ids)

    call = mock_client.post.call_args
    assert call.args[0] == "/repos/acme/app/issues"
    body = call.kwargs["json"]
    assert "t_flaky" in body["title"]
    assert "0.60" in body["body"] or "0.6" in body["body"]
    assert body["labels"] == ["flakeradar"]

    from app.models import TestCase
    tc = db_session.get(TestCase, ids[0])
    assert tc.github_issue_number == 77


def test_does_not_refile_existing_issue(db_session, monkeypatch):
    ids = _make_flaky_test(db_session)
    _configure(monkeypatch)

    from app.models import TestCase
    db_session.get(TestCase, ids[0]).github_issue_number = 5
    db_session.commit()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    with patch("app.github_integration.httpx.Client", return_value=mock_client):
        github_integration.file_issues_for(db_session, ids)
    mock_client.post.assert_not_called()


def test_below_threshold_not_filed(db_session, monkeypatch):
    result = ingest_report(
        db_session, make_junit([("t_ok", "passed")]), "sha1", "main", ""
    )
    _configure(monkeypatch)
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    with patch("app.github_integration.httpx.Client", return_value=mock_client):
        github_integration.file_issues_for(db_session, result["touched_test_ids"])
    mock_client.post.assert_not_called()


def test_api_error_never_raises(db_session, monkeypatch):
    ids = _make_flaky_test(db_session)
    _configure(monkeypatch)
    import httpx

    with patch(
        "app.github_integration.httpx.Client",
        side_effect=httpx.ConnectError("offline"),
    ):
        github_integration.file_issues_for(db_session, ids)  # must not raise

    from app.models import TestCase
    assert db_session.get(TestCase, ids[0]).github_issue_number is None


def test_rate_limit_stops_batch(db_session, monkeypatch):
    ids = _make_flaky_test(db_session)
    ingest_report(db_session, make_junit([("t_flaky2", "failed")]), "sha9", "main", "")
    result = ingest_report(
        db_session, make_junit([("t_flaky2", "passed")]), "sha9", "main", ""
    )
    all_ids = ids + result["touched_test_ids"]
    _configure(monkeypatch)

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    resp = MagicMock(status_code=403, headers={"x-ratelimit-remaining": "0"})
    mock_client.post.return_value = resp
    with patch("app.github_integration.httpx.Client", return_value=mock_client):
        github_integration.file_issues_for(db_session, all_ids)
    assert mock_client.post.call_count == 1  # stopped after the 403
