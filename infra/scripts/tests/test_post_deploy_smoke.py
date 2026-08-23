import io
import urllib.error

import pytest

from infra.scripts import post_deploy_smoke


def test_request_reports_bounded_http_diagnostics(monkeypatch) -> None:
    http_error = urllib.error.HTTPError(
        "https://example.test/api/coach",
        503,
        "Service Unavailable",
        {"X-Correlation-ID": "trace-123"},
        io.BytesIO(
            b'{"detail":"The AI service is temporarily unable to generate a validated response."}'
        ),
    )

    def fail_request(*args, **kwargs):
        del args, kwargs
        raise http_error

    monkeypatch.setattr(urllib.request, "urlopen", fail_request)

    with pytest.raises(
        post_deploy_smoke.SmokeRequestError,
        match=(
            "HTTP 503; correlation_id=trace-123; "
            "detail=The AI service is temporarily unable"
        ),
    ):
        post_deploy_smoke.request(
            "https://example.test/api/coach",
            method="POST",
            body={"message": "synthetic smoke request"},
            api_key="not-printed",
        )


def test_request_omits_unstructured_error_body(monkeypatch) -> None:
    http_error = urllib.error.HTTPError(
        "https://example.test/api/coach",
        502,
        "Bad Gateway",
        {},
        io.BytesIO(b"upstream internal response that must not be copied"),
    )

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(http_error),
    )

    with pytest.raises(post_deploy_smoke.SmokeRequestError) as raised:
        post_deploy_smoke.request("https://example.test/health")

    assert "response detail unavailable" in str(raised.value)
    assert "upstream internal response" not in str(raised.value)
