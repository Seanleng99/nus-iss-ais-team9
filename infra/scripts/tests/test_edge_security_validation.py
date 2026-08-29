import io
import urllib.error

import pytest

from infra.scripts import edge_security_validation


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"ok") -> None:
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.body


def test_direct_origin_accepts_explicit_listener_denial(monkeypatch) -> None:
    def deny(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            "http://origin.example/_stcore/health",
            403,
            "Forbidden",
            {},
            io.BytesIO(b""),
        )

    monkeypatch.setattr(edge_security_validation.urllib.request, "urlopen", deny)

    assert (
        edge_security_validation.check_direct_origin_denied(
            "http://origin.example"
        )
        == "http_403"
    )


def test_direct_origin_accepts_network_level_denial(monkeypatch) -> None:
    def deny(*_args, **_kwargs):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(edge_security_validation.urllib.request, "urlopen", deny)

    assert (
        edge_security_validation.check_direct_origin_denied(
            "http://origin.example"
        )
        == "network_denied"
    )


def test_direct_origin_rejects_reachable_health_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(
        edge_security_validation.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: FakeResponse(200),
    )

    with pytest.raises(AssertionError, match="direct origin bypass is reachable"):
        edge_security_validation.check_direct_origin_denied(
            "http://origin.example"
        )


def test_validation_enforces_expected_custom_domain(monkeypatch) -> None:
    monkeypatch.setattr(edge_security_validation, "check_frontend_health", lambda *_: None)
    monkeypatch.setattr(
        edge_security_validation,
        "check_direct_origin_denied",
        lambda *_: "network_denied",
    )
    monkeypatch.setattr(
        edge_security_validation,
        "negotiated_tls_version",
        lambda *_: "TLSv1.3",
    )

    evidence = edge_security_validation.validate(
        "https://coach.example.com",
        "http://origin.example.com",
        "coach.example.com",
    )

    assert evidence["passed"] is True
    assert evidence["custom_domain_verified"] is True
    assert evidence["direct_origin_result"] == "network_denied"


def test_validation_rejects_wrong_custom_domain() -> None:
    with pytest.raises(AssertionError, match="does not match"):
        edge_security_validation.validate(
            "https://wrong.example.com",
            "http://origin.example.com",
            "coach.example.com",
        )
