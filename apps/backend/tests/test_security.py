from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core import security
from app.core.config import Settings, settings
from app.core.security import AuthenticatedPrincipal, OidcTokenVerifier
from app.main import app

client = TestClient(app)


class StubTokenVerifier:
    def verify(self, token: str) -> AuthenticatedPrincipal:
        if token not in {"alice-token", "bob-token"}:
            raise ValueError("invalid token")
        return AuthenticatedPrincipal(
            authentication_method="oidc",
            issuer="https://issuer.example",
            subject=token.removesuffix("-token"),
        )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_oidc_verifier_enforces_signature_audience_issuer_and_token_use() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    configured = Settings(
        OIDC_ISSUER_URL="https://issuer.example",
        OIDC_JWKS_URL="https://issuer.example/.well-known/jwks.json",
        OIDC_CLIENT_ID="coach-client",
        OIDC_REQUIRED_TOKEN_USE="id",
    )
    verifier = OidcTokenVerifier(configured)
    verifier._jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=private_key.public_key())
    )
    now = datetime.now(UTC)
    claims = {
        "iss": "https://issuer.example",
        "aud": "coach-client",
        "sub": "alice",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "token_use": "id",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")

    principal = verifier.verify(token)

    assert principal.subject == "alice"
    assert principal.issuer == "https://issuer.example"
    wrong_audience = jwt.encode(
        {**claims, "aud": "other-client"}, private_key, algorithm="RS256"
    )
    with pytest.raises(jwt.InvalidAudienceError):
        verifier.verify(wrong_audience)
    access_token = jwt.encode(
        {**claims, "token_use": "access"}, private_key, algorithm="RS256"
    )
    with pytest.raises(ValueError, match="token use"):
        verifier.verify(access_token)


def test_oidc_profiles_and_resources_are_owner_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(security, "get_oidc_token_verifier", StubTokenVerifier)

    alice_profile = client.post(
        "/api/profiles",
        headers=_bearer("alice-token"),
        json={"user_id": "alice-profile", "preferences": {"display_name": "Alice"}},
    )
    bob_profile = client.post(
        "/api/profiles",
        headers=_bearer("bob-token"),
        json={"user_id": "bob-profile", "preferences": {"display_name": "Bob"}},
    )
    alice_profiles = client.get("/api/profiles", headers=_bearer("alice-token"))
    cross_profile = client.get(
        "/api/users/bob-profile/profile", headers=_bearer("alice-token")
    )
    cross_transaction = client.post(
        "/api/users/bob-profile/transactions",
        headers=_bearer("alice-token"),
        json={
            "description": "Unauthorized",
            "category": "other",
            "amount": {"currency": "SGD", "amount": 10},
            "occurred_on": "2026-08-29",
        },
    )
    cross_coach = client.post(
        "/api/coach",
        headers=_bearer("alice-token"),
        json={
            "user_id": "bob-profile",
            "session_id": "cross-owner-session",
            "message": "Can I access this profile?",
        },
    )
    malformed = client.get(
        "/api/profiles", headers={"Authorization": "Basic invalid"}
    )

    assert alice_profile.status_code == 201
    assert bob_profile.status_code == 201
    assert [profile["user_id"] for profile in alice_profiles.json()] == ["alice-profile"]
    assert cross_profile.status_code == 404
    assert cross_transaction.status_code == 404
    assert cross_coach.status_code == 404
    assert malformed.status_code == 401
    assert malformed.headers["WWW-Authenticate"] == "Bearer"


def test_existing_unowned_profile_cannot_be_claimed(monkeypatch: pytest.MonkeyPatch) -> None:
    automation_headers = {"X-API-Key": settings.api_key}
    created = client.post(
        "/api/profiles",
        headers=automation_headers,
        json={"user_id": "legacy-profile"},
    )
    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(security, "get_oidc_token_verifier", StubTokenVerifier)

    claim = client.post(
        "/api/profiles",
        headers=_bearer("alice-token"),
        json={"user_id": "legacy-profile"},
    )
    read = client.get(
        "/api/users/legacy-profile/profile",
        headers=_bearer("alice-token"),
    )

    assert created.status_code == 201
    assert claim.status_code == 409
    assert read.status_code == 404


def test_invalid_bearer_is_not_downgraded_to_automation_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(security, "get_oidc_token_verifier", StubTokenVerifier)

    response = client.get(
        "/api/profiles",
        headers={
            "Authorization": "Bearer invalid-token",
            "X-API-Key": settings.api_key,
        },
    )

    assert response.status_code == 401


def test_deployed_automation_identity_is_limited_to_synthetic_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "app_env", "demo")
    headers = {"X-API-Key": settings.api_key}

    denied = client.post(
        "/api/profiles",
        headers=headers,
        json={"user_id": "personal-profile"},
    )
    allowed = client.post(
        "/api/profiles",
        headers=headers,
        json={"user_id": "deployment-security-test"},
    )

    assert denied.status_code == 404
    assert allowed.status_code == 201


def test_authenticated_user_cannot_claim_automation_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "oidc_auth_enabled", True)
    monkeypatch.setattr(security, "get_oidc_token_verifier", StubTokenVerifier)

    response = client.post(
        "/api/profiles",
        headers=_bearer("alice-token"),
        json={"user_id": "deployment-personal-profile"},
    )

    assert response.status_code == 422
