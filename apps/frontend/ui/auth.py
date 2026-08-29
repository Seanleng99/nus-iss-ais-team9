import os
import time

import streamlit as st


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
        st.title("Financial Wellness Coach")
        st.caption("Sign in to access your private financial workspace.")
        if st.button("Sign in", type="primary"):
            st.login()
        st.stop()

    expires_at = st.user.get("exp")
    if isinstance(expires_at, (int, float)) and expires_at <= time.time():
        st.warning("Your session has expired. Please sign in again.")
        st.logout()
        st.stop()

    if current_identity_token() is None:
        st.error("The identity provider did not return a usable identity token.")
        if st.button("Sign out"):
            st.logout()
        st.stop()


def signed_in_label() -> str | None:
    if not authentication_required() or not _is_logged_in():
        return None
    for claim in ("name", "email", "preferred_username", "sub"):
        value = st.user.get(claim)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "Authenticated user"
