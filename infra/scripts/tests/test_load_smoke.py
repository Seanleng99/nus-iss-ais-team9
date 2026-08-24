import urllib.error

from infra.scripts import load_smoke
from infra.scripts.load_smoke import (
    build_report,
    chat_session_delete_url,
    cleanup_session,
    percentile,
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
