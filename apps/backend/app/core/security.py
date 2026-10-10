import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from jwt import PyJWKClient, PyJWTError
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.core.telemetry import log_event, trace_method
from app.infrastructure.database import get_db_session
from app.infrastructure.models import UserRecord


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    authentication_method: str
    issuer: str | None = None
    subject: str | None = None

    @property
    def is_automation(self) -> bool:
        log_event("VV entering ", "app.core.security.AuthenticatedPrincipal", "is_automation")
        return self.authentication_method == "automation_api_key"


class OidcTokenVerifier:
    def __init__(self, configured_settings: Settings) -> None:
        log_event("VV entering ", "app.core.security.OidcTokenVerifier", "__init__")
        self.issuer = (configured_settings.oidc_issuer_url or "").rstrip("/")
        self.audience = configured_settings.oidc_client_id or ""
        self.legacy_issuer = (
            configured_settings.oidc_legacy_issuer_url or ""
        ).rstrip("/")
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

    @trace_method
    def verify(self, token: str) -> AuthenticatedPrincipal:
        log_event("VV entering ", "app.core.security.OidcTokenVerifier", "verify")
        try:
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
            legacy_subject = claims.get("custom:legacy_sub")
            if legacy_subject is not None and (
                not self.legacy_issuer
                or not isinstance(legacy_subject, str)
                or not legacy_subject.strip()
                or len(legacy_subject) > 255
            ):
                raise ValueError("OIDC legacy identity is invalid")
        except (PyJWTError, ValueError) as error:
            log_event(
                "auth.oidc.denied", reason_code="token_verification_failed",
                exception_type=type(error).__name__, authenticated=False,
            )
            raise
        log_event("auth.oidc.accepted", authentication_method="oidc", authenticated=True)
        if legacy_subject is not None:
            return AuthenticatedPrincipal(
                authentication_method="oidc",
                issuer=self.legacy_issuer,
                subject=legacy_subject.strip(),
            )
        return AuthenticatedPrincipal(
            authentication_method="oidc",
            issuer=self.issuer,
            subject=subject,
        )


@lru_cache(maxsize=1)
def get_oidc_token_verifier() -> OidcTokenVerifier:
    log_event("VV entering ", "app.core.security", "get_oidc_token_verifier")
    return OidcTokenVerifier(settings)


def _unauthorized(reason_code: str = "authentication_required") -> HTTPException:
    log_event("VV entering ", "app.core.security", "_unauthorized")
    log_event("auth.denied", reason_code=reason_code, authenticated=False, status_code=401)
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


@trace_method
def require_principal(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> AuthenticatedPrincipal:
    log_event("VV entering ", "app.core.security", "require_principal")
    if authorization is not None:
        if not settings.oidc_auth_enabled:
            raise _unauthorized("oidc_disabled")
        scheme, separator, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not separator or not token.strip():
            raise _unauthorized("invalid_authorization_scheme")
        try:
            principal = get_oidc_token_verifier().verify(token.strip())
        except (PyJWTError, ValueError):
            raise _unauthorized("token_verification_failed") from None
        log_event("auth.accepted", authentication_method="oidc", authenticated=True)
        return principal

    if (
        settings.automation_api_key_enabled
        and x_api_key
        and secrets.compare_digest(x_api_key, settings.api_key)
    ):
        log_event(
            "auth.accepted", authentication_method="automation_api_key", authenticated=True
        )
        return AuthenticatedPrincipal(authentication_method="automation_api_key")
    raise _unauthorized()


@trace_method
def enforce_user_access(
    principal: AuthenticatedPrincipal,
    session: Session,
    user_id: str,
) -> None:
    log_event("VV entering ", "app.core.security", "enforce_user_access")
    if principal.is_automation:
        enforce_automation_user_scope(principal, user_id)
        log_event("auth.access.accepted", allowed=True, reason_code="automation_scope")
        return
    user = session.get(UserRecord, user_id)
    if (
        user is None
        or user.owner_issuer != principal.issuer
        or user.owner_subject != principal.subject
    ):
        log_event("auth.access.denied", allowed=False, reason_code="profile_not_accessible")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    log_event("auth.access.accepted", allowed=True, reason_code="profile_owned")


def automation_user_id_reserved(user_id: str) -> bool:
    log_event("VV entering ", "app.core.security", "automation_user_id_reserved")
    return any(
        user_id.startswith(prefix)
        for prefix in settings.automation_user_id_prefix_list
    )


def automation_user_id_allowed(user_id: str) -> bool:
    log_event("VV entering ", "app.core.security", "automation_user_id_allowed")
    return (
        settings.app_env.casefold() == "local"
        or automation_user_id_reserved(user_id)
    )


@trace_method
def enforce_automation_user_scope(
    principal: AuthenticatedPrincipal,
    user_id: str,
) -> None:
    log_event("VV entering ", "app.core.security", "enforce_automation_user_scope")
    if principal.is_automation and not automation_user_id_allowed(user_id):
        log_event("auth.scope.denied", allowed=False, reason_code="automation_scope")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    log_event("auth.scope.accepted", allowed=True, reason_code="automation_scope")


@trace_method
def require_owned_path_user(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_principal)],
    session: Annotated[Session, Depends(get_db_session)],
) -> AuthenticatedPrincipal:
    log_event("VV entering ", "app.core.security", "require_owned_path_user")
    user_id = request.path_params.get("user_id")
    if user_id is not None:
        enforce_user_access(principal, session, str(user_id))
    return principal
