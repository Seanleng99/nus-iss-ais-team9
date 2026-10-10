from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.telemetry import log_event, trace_method

router = APIRouter()


@trace_method
def add_cognito_logout_uri(
    provider_metadata: dict[str, Any], logout_uri: str
) -> dict[str, Any]:
    log_event("VV entering ", "app.api.oidc", "add_cognito_logout_uri")
    metadata = dict(provider_metadata)
    endpoint = metadata.get("end_session_endpoint")
    parsed_endpoint = urlparse(endpoint) if isinstance(endpoint, str) else None
    parsed_logout_uri = urlparse(logout_uri)
    if (
        parsed_endpoint is None
        or parsed_endpoint.scheme != "https"
        or not parsed_endpoint.netloc
    ):
        raise ValueError("OIDC end_session_endpoint must be an absolute HTTPS URL")
    if parsed_logout_uri.scheme != "https" or not parsed_logout_uri.netloc:
        raise ValueError("OIDC logout_uri must be an absolute HTTPS URL")

    parameters = dict(parse_qsl(parsed_endpoint.query, keep_blank_values=True))
    parameters["logout_uri"] = logout_uri
    metadata["end_session_endpoint"] = parsed_endpoint._replace(
        query=urlencode(parameters)
    ).geturl()
    return metadata


@lru_cache(maxsize=1)
@trace_method
def load_compatible_oidc_metadata() -> dict[str, Any]:
    log_event("VV entering ", "app.api.oidc", "load_compatible_oidc_metadata")
    if not settings.oidc_metadata_proxy_enabled:
        raise ValueError("OIDC metadata compatibility endpoint is disabled")
    if not settings.oidc_server_metadata_url or not settings.frontend_url:
        raise ValueError("OIDC metadata compatibility endpoint is not configured")

    response = httpx.get(
        settings.oidc_server_metadata_url,
        timeout=5.0,
        follow_redirects=False,
    )
    response.raise_for_status()
    metadata = response.json()
    if not isinstance(metadata, dict):
        raise TypeError("OIDC provider metadata must be an object")
    if metadata.get("issuer") != settings.oidc_issuer_url:
        raise ValueError("OIDC provider metadata issuer does not match configuration")
    if metadata.get("jwks_uri") != settings.oidc_jwks_url:
        raise ValueError("OIDC provider metadata JWKS URL does not match configuration")

    logout_uri = f"{settings.frontend_url.rstrip('/')}/"
    return add_cognito_logout_uri(metadata, logout_uri)


@router.get("/oidc/metadata")
@trace_method
def oidc_metadata() -> dict[str, Any]:
    log_event("VV entering ", "app.api.oidc", "oidc_metadata")
    try:
        return load_compatible_oidc_metadata()
    except (httpx.HTTPError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OIDC provider metadata is temporarily unavailable.",
        ) from None
