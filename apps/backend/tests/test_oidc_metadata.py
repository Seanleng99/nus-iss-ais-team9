from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.api import oidc
from app.core.config import Settings, settings
from app.main import app

client = TestClient(app)


class StubMetadataResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "issuer": "https://issuer.example/pool",
            "jwks_uri": "https://issuer.example/pool/jwks.json",
            "authorization_endpoint": "https://auth.example/oauth2/authorize",
            "token_endpoint": "https://auth.example/oauth2/token",
            "end_session_endpoint": "https://auth.example/logout?existing=value",
        }


def configure_metadata_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_metadata_proxy_enabled", True)
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://issuer.example/pool")
    monkeypatch.setattr(
        settings,
        "oidc_jwks_url",
        "https://issuer.example/pool/jwks.json",
    )
    monkeypatch.setattr(
        settings,
        "oidc_server_metadata_url",
        "https://issuer.example/pool/.well-known/openid-configuration",
    )
    monkeypatch.setattr(settings, "frontend_url", "https://coach.example")
    oidc.load_compatible_oidc_metadata.cache_clear()


def test_metadata_adapter_adds_cognito_logout_uri_and_caches_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_metadata_proxy(monkeypatch)
    calls: list[tuple[str, float, bool]] = []

    def fake_get(url: str, *, timeout: float, follow_redirects: bool):
        calls.append((url, timeout, follow_redirects))
        return StubMetadataResponse()

    monkeypatch.setattr(oidc.httpx, "get", fake_get)
    try:
        first = client.get("/api/oidc/metadata")
        second = client.get("/api/oidc/metadata")
    finally:
        oidc.load_compatible_oidc_metadata.cache_clear()

    assert first.status_code == 200
    assert second.status_code == 200
    endpoint = urlparse(first.json()["end_session_endpoint"])
    assert parse_qs(endpoint.query) == {
        "existing": ["value"],
        "logout_uri": ["https://coach.example/"],
    }
    assert calls == [
        (
            "https://issuer.example/pool/.well-known/openid-configuration",
            5.0,
            False,
        )
    ]


def test_metadata_adapter_fails_closed_on_provider_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_metadata_proxy(monkeypatch)

    class WrongIssuerResponse(StubMetadataResponse):
        def json(self) -> dict[str, object]:
            metadata = super().json()
            metadata["issuer"] = "https://attacker.example"
            return metadata

    monkeypatch.setattr(oidc.httpx, "get", lambda *args, **kwargs: WrongIssuerResponse())
    try:
        response = client.get("/api/oidc/metadata")
    finally:
        oidc.load_compatible_oidc_metadata.cache_clear()

    assert response.status_code == 502
    assert response.json() == {
        "detail": "OIDC provider metadata is temporarily unavailable."
    }


def test_deployment_metadata_adapter_requires_complete_https_configuration() -> None:
    common = {
        "APP_ENV": "demo",
        "BACKEND_API_KEY": "a-secure-service-key-that-is-long-enough",
        "AI_SERVICE_API_KEY": "another-secure-service-key-long-enough",
        "POSTGRES_SSLMODE": "require",
        "OIDC_AUTH_ENABLED": True,
        "OIDC_METADATA_PROXY_ENABLED": True,
        "OIDC_ISSUER_URL": "https://issuer.example/pool",
        "OIDC_JWKS_URL": "https://issuer.example/pool/jwks.json",
        "OIDC_CLIENT_ID": "coach-client",
        "OIDC_REQUIRED_TOKEN_USE": "id",
    }

    with pytest.raises(
        ValueError,
        match="OIDC_SERVER_METADATA_URL, FRONTEND_URL must be configured",
    ):
        Settings(**common)
    with pytest.raises(
        ValueError,
        match="OIDC_SERVER_METADATA_URL, FRONTEND_URL must use HTTPS",
    ):
        Settings(
            **common,
            OIDC_SERVER_METADATA_URL="http://issuer.example/metadata",
            FRONTEND_URL="http://coach.example",
        )
