from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
from sqlalchemy import URL


class Settings(BaseSettings):
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_key: str = Field(default="change-me-locally", alias="BACKEND_API_KEY")
    ai_service_base_url: str = Field(
        default="http://localhost:8001", alias="AI_SERVICE_BASE_URL"
    )
    ai_service_api_key: str = Field(
        default="change-me-locally", alias="AI_SERVICE_API_KEY"
    )
    ai_service_timeout_seconds: float = Field(
        default=45.0, gt=0, le=120, alias="AI_SERVICE_TIMEOUT_SECONDS"
    )
    postgres_url: str | None = Field(default=None, alias="POSTGRES_URL")
    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, ge=1, le=65535, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="financial_wellness", alias="POSTGRES_DB")
    postgres_user: str = Field(default="coach", alias="POSTGRES_USER")
    postgres_password: str = Field(default="coach", alias="POSTGRES_PASSWORD")
    postgres_sslmode: str = Field(default="prefer", alias="POSTGRES_SSLMODE")

    @property
    def database_url(self) -> URL | str:
        if self.postgres_host:
            return URL.create(
                "postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
                query={"sslmode": self.postgres_sslmode},
            )

        url = self.postgres_url or (
            "postgresql://coach:coach@localhost:5432/financial_wellness"
        )
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    @model_validator(mode="after")
    def require_deployment_secrets(self) -> Self:
        if self.app_env.lower() != "local":
            invalid = [
                name
                for name, value in (
                    ("BACKEND_API_KEY", self.api_key),
                    ("AI_SERVICE_API_KEY", self.ai_service_api_key),
                )
                if value == "change-me-locally" or len(value) < 20
            ]
            if invalid:
                raise ValueError(
                    f"{', '.join(invalid)} must be non-default values of at least 20 characters"
                )
            if self.postgres_sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("POSTGRES_SSLMODE must require TLS outside local development")
        return self


settings = Settings()
