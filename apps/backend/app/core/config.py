from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


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
    postgres_url: str = Field(
        default="postgresql://coach:coach@localhost:5432/financial_wellness",
        alias="POSTGRES_URL",
    )

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
        return self


settings = Settings()
