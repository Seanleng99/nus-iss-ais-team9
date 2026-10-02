import json
import runpy
import traceback
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, call

import psycopg
import pytest
from alembic import command, context
from alembic.config import Config
from sqlalchemy import URL, create_engine
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg

from app.core import config as config_module
from app.core.config import Settings
from app.infrastructure import database
from app.infrastructure.database import (
    configure_database_credentials,
    render_alembic_database_url,
)

SECRET_ARN = "arn:aws:secretsmanager:ap-southeast-1:123456789012:secret:test-db-abcdef"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def secret_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    for name in ("APP_ENV", "POSTGRES_URL", "POSTGRES_HOST", "POSTGRES_SECRET_ARN", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    return Settings(
        POSTGRES_HOST="database.example",
        POSTGRES_PORT=5433,
        POSTGRES_DB="test_db",
        POSTGRES_USER="startup-user",
        POSTGRES_PASSWORD="startup-password",
        POSTGRES_SSLMODE="require",
        POSTGRES_SECRET_ARN=SECRET_ARN,
        AWS_REGION="ap-southeast-1",
    )


@pytest.fixture
def fake_secrets(monkeypatch: pytest.MonkeyPatch) -> tuple[Mock, Mock]:
    client = Mock()
    client.get_secret_value.return_value = {
        "SecretString": json.dumps({"username": "current-user", "password": "current-password"})
    }
    session = Mock()
    session.client.return_value = client
    factory = Mock(return_value=session)
    monkeypatch.setattr(database.boto3.session, "Session", factory)
    return factory, client


@pytest.fixture
def fake_dbapi_connect(monkeypatch: pytest.MonkeyPatch) -> Mock:
    # Exercise real SQLAlchemy connections/pooling without PostgreSQL initialization or I/O.
    monkeypatch.setattr(PGDialect_psycopg, "on_connect", lambda self: None)
    monkeypatch.setattr(PGDialect_psycopg, "initialize", lambda self, connection: None)
    connect = Mock(side_effect=lambda *args, **kwargs: Mock(spec=["rollback", "commit", "close"]))
    monkeypatch.setattr(psycopg, "connect", connect)
    return connect


def test_alembic_url_escapes_percent_encoded_password() -> None:
    database_url = URL.create(
        "postgresql+psycopg",
        username="coachadmin",
        password=")2:k:j(gvPIQ4coSQrGCw#3BvQ)",
        host="database.example",
        database="financial_wellness",
    )
    rendered = database_url.render_as_string(hide_password=False)
    config = Config()

    config.set_main_option("sqlalchemy.url", render_alembic_database_url(database_url))

    assert "%29" in rendered
    assert config.get_main_option("sqlalchemy.url") == rendered


@pytest.mark.parametrize("host", [None, "", " \t"])
def test_postgres_secret_requires_explicit_host(
    secret_settings: Settings, host: str | None
) -> None:
    with pytest.raises(ValueError, match="POSTGRES_HOST is required"):
        Settings(
            POSTGRES_SECRET_ARN=SECRET_ARN,
            POSTGRES_HOST=host,
            POSTGRES_URL="postgresql://user:password@url-host.example/db",
        )


@pytest.mark.parametrize("arn", ["", " \t"])
def test_postgres_secret_rejects_blank_arn(secret_settings: Settings, arn: str) -> None:
    with pytest.raises(ValueError, match="POSTGRES_SECRET_ARN must not be blank"):
        Settings(POSTGRES_HOST="database.example", POSTGRES_SECRET_ARN=arn)


def test_secret_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("POSTGRES_HOST", "database.example")
    monkeypatch.setenv("POSTGRES_SECRET_ARN", SECRET_ARN)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")

    configured = Settings()

    assert configured.postgres_secret_arn == SECRET_ARN
    assert configured.aws_region == "ap-southeast-1"


def test_credentials_refresh_only_for_new_physical_connections(
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
) -> None:
    factory, client = fake_secrets
    credentials = [
        {"username": "first-user", "password": "first-password"},
        {"username": "second-user", "password": " rotated%@:/?# password "},
    ]
    client.get_secret_value.side_effect = [
        {"SecretString": json.dumps({**value, "host": "ignored.example", "port": 1})}
        for value in credentials
    ]
    engine = create_engine(secret_settings.database_url)
    _, original_parameters = engine.dialect.create_connect_args(engine.url)
    configure_database_credentials(engine, secret_settings)
    factory.assert_not_called()
    client.get_secret_value.assert_not_called()

    try:
        with engine.connect():
            pass
        with engine.connect():  # A pooled checkout reuses the existing physical connection.
            pass
        assert client.get_secret_value.call_count == 1
        engine.dispose()
        with engine.connect():
            pass
    finally:
        engine.dispose()

    assert client.get_secret_value.call_args_list == [
        call(SecretId=SECRET_ARN, VersionStage="AWSCURRENT"),
        call(SecretId=SECRET_ARN, VersionStage="AWSCURRENT"),
    ]
    assert [entry.kwargs for entry in fake_dbapi_connect.call_args_list] == [
        {
            **original_parameters,
            "host": "database.example",
            "port": 5433,
            "dbname": "test_db",
            "sslmode": "require",
            "user": value["username"],
            "password": value["password"],
        }
        for value in credentials
    ]
    assert engine.url == secret_settings.database_url
    assert secret_settings.postgres_password == "startup-password"
    factory.assert_called_once_with()
    factory.return_value.client.assert_called_once()
    args, kwargs = factory.return_value.client.call_args
    assert args == ("secretsmanager",)
    assert kwargs["region_name"] == "ap-southeast-1"
    assert kwargs["config"].connect_timeout == 2
    assert kwargs["config"].read_timeout == 2
    assert kwargs["config"].retries == {"mode": "standard", "total_max_attempts": 2}


@pytest.mark.parametrize("mode", ["default", "url", "host", "sqlite"])
def test_static_configuration_never_creates_secret_client(
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
    mode: str,
) -> None:
    factory, client = fake_secrets
    options = {
        "default": {},
        "url": {"POSTGRES_URL": "postgresql://url-user:url-password@url.example/url-db"},
        "host": {
            "POSTGRES_HOST": "static.example",
            "POSTGRES_USER": "static-user",
            "POSTGRES_PASSWORD": "static-password",
        },
        "sqlite": {"POSTGRES_URL": "sqlite+pysqlite:///:memory:"},
    }
    configured = Settings(**options[mode])
    engine = create_engine(configured.database_url)
    expected_args, expected_params = engine.dialect.create_connect_args(engine.url)
    configure_database_credentials(engine, configured)
    try:
        with engine.connect():
            pass
    finally:
        engine.dispose()

    factory.assert_not_called()
    client.get_secret_value.assert_not_called()
    if mode == "sqlite":
        fake_dbapi_connect.assert_not_called()
    else:
        fake_dbapi_connect.assert_called_once_with(*expected_args, **expected_params)


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {},
        {"SecretBinary": b"sensitive-secret-body"},
        {"SecretString": None},
        {"SecretString": 123},
        {"SecretString": b"{}"},
        {"SecretString": "sensitive-secret-body"},
        *(
            {"SecretString": json.dumps(value)}
            for value in [None, [], 42, "sensitive-secret-body", {}]
        ),
        *(
            {
                "SecretString": json.dumps(
                    {"username": "valid-user", "password": "valid-password", key: value}
                )
            }
            for key in ("username", "password")
            for value in (None, 42, True, [], {}, "", " \t", "sensitive\u0000secret-body")
        ),
    ],
)
def test_invalid_secret_payload_fails_safely(
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
    response: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, client = fake_secrets
    client.get_secret_value.return_value = response
    engine = create_engine(secret_settings.database_url)
    configure_database_credentials(engine, secret_settings)
    try:
        with pytest.raises(RuntimeError) as caught:
            engine.connect()
    finally:
        engine.dispose()

    assert str(caught.value) == "Unable to load database credentials"
    assert caught.value.__suppress_context__ is True
    assert "secret-body" not in "".join(traceback.format_exception(caught.value)) + caplog.text
    fake_dbapi_connect.assert_not_called()


@pytest.mark.parametrize("failure_stage", ["session", "client", "lookup"])
def test_secret_provider_failure_is_safe_and_next_connection_can_recover(
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
    failure_stage: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    factory, client = fake_secrets
    failing_call = {
        "session": factory,
        "client": factory.return_value.client,
        "lookup": client.get_secret_value,
    }[failure_stage]
    failing_call.side_effect = RuntimeError("sensitive-provider-message")
    engine = create_engine(secret_settings.database_url)
    configure_database_credentials(engine, secret_settings)
    try:
        with pytest.raises(RuntimeError) as caught:
            engine.connect()
        assert str(caught.value) == "Unable to load database credentials"
        assert "sensitive-provider-message" not in (
            "".join(traceback.format_exception(caught.value)) + caplog.text
        )
        fake_dbapi_connect.assert_not_called()

        failing_call.side_effect = None
        with engine.connect():
            pass
        assert fake_dbapi_connect.call_args.kwargs["password"] == "current-password"
    finally:
        engine.dispose()


def test_backend_engine_registers_refresh_without_eager_lookup(
    monkeypatch: pytest.MonkeyPatch,
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
) -> None:
    monkeypatch.setattr(config_module, "settings", secret_settings)
    runtime = runpy.run_path(str(Path(database.__file__)))
    engine = runtime["engine"]
    fake_secrets[0].assert_not_called()
    try:
        assert runtime["SessionLocal"].kw["bind"] is engine
        with engine.connect():
            pass
        assert fake_dbapi_connect.call_args.kwargs["password"] == "current-password"
    finally:
        engine.dispose()


@pytest.mark.parametrize("use_secret", [True, False])
def test_online_migrations_use_same_credentials(
    monkeypatch: pytest.MonkeyPatch,
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
    use_secret: bool,
) -> None:
    configured = secret_settings.model_copy(
        update={"postgres_secret_arn": SECRET_ARN if use_secret else None}
    )
    monkeypatch.setattr(config_module, "settings", configured)
    run_migrations = Mock()
    monkeypatch.setattr(context, "run_migrations", run_migrations)
    config = Config()
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))

    command.upgrade(config, "head")

    run_migrations.assert_called_once()
    assert fake_dbapi_connect.call_count == 1
    assert fake_dbapi_connect.call_args.kwargs["password"] == (
        "current-password" if use_secret else "startup-password"
    )
    if use_secret:
        fake_secrets[1].get_secret_value.assert_called_once_with(
            SecretId=SECRET_ARN, VersionStage="AWSCURRENT"
        )
    else:
        fake_secrets[0].assert_not_called()


def test_offline_migrations_generate_sql_without_secret_lookup(
    monkeypatch: pytest.MonkeyPatch,
    secret_settings: Settings,
    fake_secrets: tuple[Mock, Mock],
    fake_dbapi_connect: Mock,
) -> None:
    monkeypatch.setattr(config_module, "settings", secret_settings)
    output = StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))

    command.upgrade(config, "head", sql=True)

    assert "CREATE TABLE" in output.getvalue()
    assert "alembic_version" in output.getvalue()
    assert "ADD COLUMN conversation_state JSON" in output.getvalue()
    assert "ADD COLUMN pending_transaction JSON" in output.getvalue()
    fake_secrets[0].assert_not_called()
    fake_secrets[1].get_secret_value.assert_not_called()
    fake_dbapi_connect.assert_not_called()


@pytest.mark.parametrize(
    "previous_head,missing_column,existing_column",
    [
        ("20261001_0014", "conversation_state", "pending_transaction"),
        ("20261002_0014", "pending_transaction", "conversation_state"),
    ],
)
def test_chat_state_merge_upgrades_from_either_existing_head(
    previous_head, missing_column, existing_column, monkeypatch, secret_settings, fake_secrets,
):
    monkeypatch.setattr(config_module, "settings", secret_settings)
    output = StringIO()
    config = Config(output_buffer=output)
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))

    command.upgrade(config, f"{previous_head}:head", sql=True)

    sql = output.getvalue()
    assert f"ADD COLUMN {missing_column} JSON" in sql
    assert f"ADD COLUMN {existing_column} JSON" not in sql
    assert "20261002_0015" in sql
    fake_secrets[0].assert_not_called()
