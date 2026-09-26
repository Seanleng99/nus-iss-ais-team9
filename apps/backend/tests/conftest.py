from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.infrastructure.database import Base, get_db_session
from app.main import app


@pytest.fixture(autouse=True)
def isolated_database() -> Generator[None, None, None]:
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        test_engine.dispose()


@pytest.fixture
def db_session_factory() -> Generator[sessionmaker, None, None]:
    """Yield the isolated test session factory so tests can create sessions directly."""
    test_engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    test_session = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        yield test_session
    finally:
        app.dependency_overrides.pop(get_db_session, None)
        test_engine.dispose()
