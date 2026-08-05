from collections.abc import Generator

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

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
    rendered = (
        database_url.render_as_string(hide_password=False)
        if isinstance(database_url, URL)
        else database_url
    )
    # Alembic stores this value in ConfigParser, where literal percent signs must be doubled.
    return rendered.replace("%", "%%")


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_recycle=300,
    hide_parameters=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session
