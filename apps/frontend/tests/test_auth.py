import tomllib

import pytest
from streamlit.auth_util import generate_default_provider_section
from streamlit.runtime.secrets import AttrDict

from entrypoint import render_auth_secrets


def test_runtime_auth_configuration_uses_public_client_pkce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "https://coach.example/oauth2callback")
    monkeypatch.setenv("OIDC_CLIENT_ID", "public-client")
    monkeypatch.setenv(
        "OIDC_SERVER_METADATA_URL",
        "https://issuer.example/.well-known/openid-configuration",
    )
    monkeypatch.setenv("OIDC_COOKIE_SECRET", "x" * 64)

    configuration = tomllib.loads(render_auth_secrets())

    assert (
        configuration["auth"]["client_secret"]
        == "streamlit-public-client-placeholder"
    )
    assert configuration["auth"]["expose_tokens"] == "id"
    assert configuration["auth"]["client_kwargs"] == {
        "prompt": "login",
        "token_endpoint_auth_method": "none",
        "code_challenge_method": "S256",
    }
    provider = generate_default_provider_section(AttrDict(configuration["auth"]))
    assert {"client_id", "client_secret", "server_metadata_url"}.issubset(provider)


def test_runtime_auth_configuration_rejects_insecure_demo_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "demo")
    monkeypatch.setenv("OIDC_REDIRECT_URI", "http://coach.example/oauth2callback")
    monkeypatch.setenv("OIDC_CLIENT_ID", "public-client")
    monkeypatch.setenv(
        "OIDC_SERVER_METADATA_URL",
        "https://issuer.example/.well-known/openid-configuration",
    )
    monkeypatch.setenv("OIDC_COOKIE_SECRET", "x" * 64)

    with pytest.raises(RuntimeError, match="OIDC_REDIRECT_URI must use HTTPS"):
        render_auth_secrets()
