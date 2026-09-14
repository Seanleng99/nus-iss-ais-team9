import os
import time
from contextlib import nullcontext
from uuid import uuid4

import streamlit as st

from ui.telemetry import call_span, context_fields, log_event, trace_context


def _clear_authenticated_session() -> None:
    for key in list(st.session_state):
        if key.startswith("coach_") or key in {
            "journey_id", "auth_identity", "auth_status", "backend_client",
            "backend_client_identity_token", "backend_client_journey_id", "active_user_id",
        }:
            st.session_state.pop(key, None)


def logout(reason_code: str = "user_requested") -> None:
    with (
        nullcontext() if context_fields().get("correlation_id")
        else trace_context(journey_id=st.session_state.get("journey_id"))
    ), call_span(f"{__name__}.logout"):
        _clear_authenticated_session()
        with call_span("streamlit.user_info.logout"):
            log_event("auth.logout_requested", reason_code=reason_code)
            st.logout()


def authentication_required() -> bool:
    configured = os.getenv("FRONTEND_AUTH_REQUIRED")
    if configured is None:
        return False
    return configured.casefold() in {"1", "true", "yes", "on"}


def _is_logged_in() -> bool:
    return bool(getattr(st.user, "is_logged_in", False))


def current_identity_token() -> str | None:
    if not authentication_required():
        return None
    if not _is_logged_in():
        return None
    token = st.user.tokens.get("id")
    return token if isinstance(token, str) and token else None


def require_authenticated_user() -> None:
    if not authentication_required():
        return
    if not _is_logged_in():
        if st.session_state.get("journey_id"):
            with trace_context(journey_id=st.session_state.journey_id), call_span(
                f"{__name__}.require_authenticated_user"
            ):
                log_event("auth.session_ended", authenticated=False, reason_code="not_logged_in")
        _clear_authenticated_session()
        st.title("Financial Wellness Coach")
        st.caption("Sign in to access your private financial workspace.")
        if st.button("Sign in", type="primary"):
            # OIDC redirects create a new Streamlit session. Pre-login session_state
            # cannot reliably link to the return; start the journey after login.
            with (
                trace_context(),
                call_span(f"{__name__}.require_authenticated_user"),
                call_span("streamlit.user_info.login"),
            ):
                log_event("auth.login_requested", authentication_method="oidc")
                st.login()
        st.stop()

    identity_token = current_identity_token()
    # This comparison is private session state, never telemetry. Prefer stable OIDC
    # identity so a refreshed token does not create a second login observation.
    identity = (st.user.get("iss"), st.user.get("sub") or identity_token)
    if st.session_state.get("auth_identity") != identity:
        if st.session_state.get("auth_identity") is not None:
            with trace_context(journey_id=st.session_state.get("journey_id")), call_span(
                f"{__name__}.require_authenticated_user"
            ):
                log_event("auth.identity_changed", reason_code="identity_changed")
        _clear_authenticated_session()
        st.session_state.auth_identity = identity

    expires_at = st.user.get("exp")
    if isinstance(expires_at, (int, float)) and expires_at <= time.time():
        with trace_context(journey_id=st.session_state.get("journey_id")), call_span(
            f"{__name__}.require_authenticated_user"
        ):
            log_event("auth.session_expired", authenticated=False, reason_code="expired")
            st.warning("Your session has expired. Please sign in again.")
            logout(reason_code="expired")
        st.stop()

    if identity_token is None:
        if st.session_state.get("auth_status") != "missing_token":
            with trace_context(journey_id=st.session_state.get("journey_id")), call_span(
                f"{__name__}.require_authenticated_user"
            ):
                log_event("auth.identity_token_missing", authenticated=False, reason_code="missing_token")
            _clear_authenticated_session()
            st.session_state.auth_identity = identity
            st.session_state.auth_status = "missing_token"
        st.error("The identity provider did not return a usable identity token.")
        if st.button("Sign out"):
            logout(reason_code="missing_token")
        st.stop()

    if st.session_state.get("auth_status") != "authenticated":
        st.session_state.journey_id = uuid4().hex
        st.session_state.auth_status = "authenticated"
        with trace_context(journey_id=st.session_state.journey_id), call_span(
            f"{__name__}.require_authenticated_user"
        ):
            log_event("auth.session_authenticated", authenticated=True, authentication_method="oidc")


def signed_in_label() -> str | None:
    if not authentication_required() or not _is_logged_in():
        return None
    for claim in ("name", "email", "preferred_username", "sub"):
        value = st.user.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Authenticated user"
