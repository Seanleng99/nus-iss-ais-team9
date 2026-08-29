import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient, PyJWTError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.infrastructure.database import get_db_session
from app.infrastructure.models import UserRecord


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    authentication_method: str
    issuer: str | None = None
    subject: str | None = None

    @property
    def is_automation(self) -> bool:
        return self.authentication_method == "automation_api_key"


class OidcTokenVerifier:
    def __init__(self, configured_settings: Settings) -> None:
        self.issuer = (configured_settings.oidc_issuer_url or "").rstrip("/")
        self.audience = configured_settings.oidc_client_id or ""
        self.required_token_use = configured_settings.oidc_required_token_use
        self.clock_skew_seconds = configured_settings.oidc_clock_skew_seconds
        self._jwks_client = (
            PyJWKClient(
                configured_settings.oidc_jwks_url,
                cache_keys=True,
                lifespan=300,
            )
            if configured_settings.oidc_jwks_url
            else None
        )

    def verify(self, token: str) -> AuthenticatedPrincipal:
        if not self._jwks_client or not self.issuer or not self.audience:
            raise ValueError("OIDC verification is not configured")
        signing_key = self._jwks_client.get_signing_key_from_jwt(token).key
        claims: dict[str, Any] = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=self.audience,
            issuer=self.issuer,
            leeway=self.clock_skew_seconds,
            options={"require": ["aud", "exp", "iat", "iss", "sub"]},
        )
        subject = str(claims.get("sub", "")).strip()
        if not subject or len(subject) > 255:
            raise ValueError("OIDC subject is invalid")
        if self.required_token_use and claims.get("token_use") != self.required_token_use:
            raise ValueError("OIDC token use is invalid")
        return AuthenticatedPrincipal(
            authentication_method="oidc",
            issuer=self.issuer,
            subject=subject,
        )


@lru_cache(maxsize=1)
def get_oidc_token_verifier() -> OidcTokenVerifier:
    return OidcTokenVerifier(settings)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> AuthenticatedPrincipal:
    if authorization is not None:
        if not settings.oidc_auth_enabled:
            raise _unauthorized()
        scheme, separator, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not separator or not token.strip():
            raise _unauthorized()
        try:
            return get_oidc_token_verifier().verify(token.strip())
        except (PyJWTError, ValueError):
            raise _unauthorized() from None

    if (
        settings.automation_api_key_enabled
        and x_api_key
        and secrets.compare_digest(x_api_key, settings.api_key)
    ):
        return AuthenticatedPrincipal(authentication_method="automation_api_key")
    raise _unauthorized()


def enforce_user_access(
    principal: AuthenticatedPrincipal,
    session: Session,
    user_id: str,
) -> None:
    if principal.is_automation:
        enforce_automation_user_scope(principal, user_id)
        return
    user = session.get(UserRecord, user_id)
    if (
        user is None
        or user.owner_issuer != principal.issuer
        or user.owner_subject != principal.subject
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )


def automation_user_id_reserved(user_id: str) -> bool:
    return any(
        user_id.startswith(prefix)
        for prefix in settings.automation_user_id_prefix_list
    )


def automation_user_id_allowed(user_id: str) -> bool:
    return (
        settings.app_env.casefold() == "local"
        or automation_user_id_reserved(user_id)
    )


def enforce_automation_user_scope(
    principal: AuthenticatedPrincipal,
    user_id: str,
) -> None:
    if principal.is_automation and not automation_user_id_allowed(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )


def require_owned_path_user(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedPrincipal:
    user_id = request.path_params.get("user_id")
    if user_id is not None:
        enforce_user_access(principal, session, str(user_id))
    return principal
