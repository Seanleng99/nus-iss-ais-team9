from alembic.config import Config
from sqlalchemy import URL

from app.infrastructure.database import render_alembic_database_url


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
