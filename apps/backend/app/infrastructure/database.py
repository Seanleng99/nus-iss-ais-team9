import json
from collections.abc import Generator

import boto3
from botocore.config import Config
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings, settings
from app.core.telemetry import log_event

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def render_alembic_database_url(database_url: URL | str) -> str:
    log_event("VV entering ", "app.infrastructure.database", "render_alembic_database_url")
    rendered = (
        database_url.render_as_string(hide_password=False)
        if isinstance(database_url, URL)
        else database_url
    )
    # Alembic stores this value in ConfigParser, where literal percent signs must be doubled.
    return rendered.replace("%", "%%")


def configure_database_credentials(engine: Engine, configured: Settings) -> None:
    log_event("VV entering ", "app.infrastructure.database", "configure_database_credentials")
    if configured.postgres_secret_arn is None:
        return

    client = None

    @event.listens_for(engine, "do_connect")
    def connect_with_current_credentials(dialect, _connection_record, cargs, cparams):
        log_event("VV entering ", "app.infrastructure.database", "configure_database_credentials.connect_with_current_credentials")
        nonlocal client
        try:
            if client is None:
                client = boto3.session.Session().client(
                    "secretsmanager",
                    region_name=configured.aws_region,
                    config=Config(
                        connect_timeout=2,
                        read_timeout=2,
                        retries={"mode": "standard", "total_max_attempts": 2},
                    ),
                )
            response = client.get_secret_value(
                SecretId=configured.postgres_secret_arn,
                VersionStage="AWSCURRENT",
            )
            if not isinstance(response, dict) or not isinstance(response.get("SecretString"), str):
                raise TypeError
            payload = json.loads(response["SecretString"])
            if not isinstance(payload, dict):
                raise TypeError
            username, password = payload.get("username"), payload.get("password")
            if any(
                not isinstance(value, str) or not value.strip() or "\x00" in value
                for value in (username, password)
            ):
                raise ValueError
        except Exception:  # noqa: BLE001 - Never expose provider or secret payload details.
            raise RuntimeError("Unable to load database credentials") from None

        # Keep refreshed credentials out of the engine's shared connection parameters.
        return dialect.connect(*cargs, **{**cparams, "user": username, "password": password})


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    hide_parameters=True,
)
configure_database_credentials(engine, settings)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    log_event("VV entering ", "app.infrastructure.database", "get_db_session")
    with SessionLocal() as session:
        yield session
