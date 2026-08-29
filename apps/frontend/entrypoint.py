import json
import os
from pathlib import Path


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required when frontend authentication is enabled")
    return value


def render_auth_secrets() -> str:
    redirect_uri = _required_environment("OIDC_REDIRECT_URI")
    client_id = _required_environment("OIDC_CLIENT_ID")
    metadata_url = _required_environment("OIDC_SERVER_METADATA_URL")
    cookie_secret = _required_environment("OIDC_COOKIE_SECRET")
    if os.getenv("APP_ENV", "local").casefold() != "local":
        for name, value in (
            ("OIDC_REDIRECT_URI", redirect_uri),
            ("OIDC_SERVER_METADATA_URL", metadata_url),
        ):
            if not value.startswith("https://"):
                raise RuntimeError(f"{name} must use HTTPS outside local development")
        if len(cookie_secret) < 32:
            raise RuntimeError("OIDC_COOKIE_SECRET must contain at least 32 characters")
    values = {
        "redirect_uri": redirect_uri,
        "cookie_secret": cookie_secret,
        "client_id": client_id,
        # Streamlit requires this key even for a public OIDC client. The
        # token_endpoint_auth_method below ensures this non-secret sentinel is
        # never presented to Cognito as client authentication.
        "client_secret": "streamlit-public-client-placeholder",
        "server_metadata_url": metadata_url,
    }
    lines = ["[auth]"]
    lines.extend(f"{key} = {json.dumps(value)}" for key, value in values.items())
    lines.extend(
        [
            'expose_tokens = "id"',
            (
                'client_kwargs = { prompt = "login", '
                'token_endpoint_auth_method = "none", '
                'code_challenge_method = "S256" }'
            ),
            "",
        ]
    )
    return "\n".join(lines)


def configure_authentication() -> None:
    enabled = os.getenv("FRONTEND_AUTH_REQUIRED", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        return
    destination = Path.home() / ".streamlit" / "secrets.toml"
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(render_auth_secrets(), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(destination)


def main() -> None:
    configure_authentication()
    os.execvp(
        "streamlit",
        [
            "streamlit",
            "run",
            "app.py",
            "--server.address=0.0.0.0",
            "--server.port=8501",
            "--server.headless=true",
        ],
    )


if __name__ == "__main__":
    main()
