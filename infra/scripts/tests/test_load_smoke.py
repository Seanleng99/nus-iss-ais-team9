import json
import urllib.error

import pytest

from infra.scripts import load_smoke
from infra.scripts.load_smoke import (
    build_report,
    chat_session_delete_url,
    cleanup_session,
    percentile,
    send_request,
)


def test_chat_session_delete_url_preserves_api_prefix_and_encodes_ids() -> None:
    result = chat_session_delete_url(
        "https://example.test/api/coach?ignored=true",
        "load user",
        "session/one",
    )

    assert result == (
        "https://example.test/api/users/load%20user/chat-sessions/session%2Fone"
    )


def test_cleanup_treats_missing_synthetic_session_as_clean(monkeypatch) -> None:
    def missing(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "https://example.test/session", 404, "Not Found", {}, None
        )

    monkeypatch.setattr(load_smoke.urllib.request, "urlopen", missing)

    assert cleanup_session(
        "https://example.test/api/coach", "secret", "user", "session", 1
    ) is True


def test_send_request_isolates_each_synthetic_user(monkeypatch) -> None:
    requests = []

    class StubResponse:
        def __init__(self, status: int) -> None:
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return b"{}"

    def respond(request, timeout):
        del timeout
        requests.append(request)
        return StubResponse(200 if request.method == "POST" else 204)

    monkeypatch.setattr(load_smoke.urllib.request, "urlopen", respond)

    status, _, cleaned_up = send_request(
        "https://example.test/api/coach", "secret", 1
    )

    payload = json.loads(requests[0].data)
    user_id = payload["user_id"]
    session_id = payload["session_id"]
    assert status == 200
    assert cleaned_up is True
    assert user_id == f"load-test-user-{session_id}"
    assert f"/users/{user_id}/chat-sessions/{session_id}" in requests[1].full_url


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([10, 20, 30, 40], 0.5) == 20
    assert percentile([10, 20, 30, 40], 0.95) == 40
    assert percentile([], 0.95) is None


def test_build_report_contains_privacy_safe_operational_evidence() -> None:
    report = build_report(
        url="https://example.test/api/coach",
        request_count=4,
        concurrency=2,
        latencies=[10, 20, 30],
        failures=["TimeoutError"],
        cleanup_failures=1,
        elapsed_seconds=1.234,
        commit_sha="abc123",
    )

    assert report["target_host"] == "example.test"
    assert report["success_rate"] == 0.75
    assert report["latency_ms"] == {"p50": 20, "p95": 30, "p99": 30}
    assert report["failure_types"] == ["TimeoutError"]
    assert report["cleanup_failures"] == 1


def test_http_quota_denial_still_fails_load_and_reports_its_status(monkeypatch, capsys):
    def denied(*_args):
        raise urllib.error.HTTPError("https://example.test/api/coach", 429,
                                     "Too Many Requests", {}, None)

    monkeypatch.setattr(load_smoke, "send_request", denied)
    monkeypatch.setattr("sys.argv", ["load_smoke.py", "--url", "https://example.test/api/coach",
                                    "--api-key", "synthetic", "--requests", "1"])
    with pytest.raises(SystemExit, match="success rate was below threshold"):
        load_smoke.main()
    report = json.loads(capsys.readouterr().out)
    assert report["passed"] is False
    assert report["successes"] == 0
    assert report["failure_types"] == ["HTTP 429"]
