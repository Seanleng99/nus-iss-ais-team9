from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    model_provider: str = Field(default="bedrock", alias="MODEL_PROVIDER")
    model_id: str = Field(
        default="apac.amazon.nova-lite-v1:0",
        alias="MODEL_ID",
    )
    embedding_model_id: str = Field(
        default="amazon.titan-embed-text-v2:0",
        alias="EMBEDDING_MODEL_ID",
    )
    aws_region: str = Field(default="ap-southeast-1", alias="AWS_REGION")
    prompt_set_version: str = Field(default="v1", alias="PROMPT_SET_VERSION")
    router_temperature: float = Field(default=0.2, ge=0.01, le=1.0, alias="ROUTER_TEMPERATURE")
    agent_temperature: float = Field(default=0.35, ge=0.01, le=1.0, alias="AGENT_TEMPERATURE")
    compliance_temperature: float = Field(
        default=0.1, ge=0.01, le=1.0, alias="COMPLIANCE_TEMPERATURE"
    )
    model_max_tokens: int = Field(default=800, ge=100, le=4096, alias="MODEL_MAX_TOKENS")
    vector_store_url: str = Field(default="http://localhost:6333", alias="VECTOR_STORE_URL")
    api_key: str = Field(default="change-me-locally", alias="AI_SERVICE_API_KEY")

    @model_validator(mode="after")
    def require_deployment_api_key(self) -> Self:
        if self.app_env.lower() != "local" and (
            self.api_key == "change-me-locally" or len(self.api_key) < 20
        ):
            raise ValueError("AI_SERVICE_API_KEY must be a non-default value of at least 20 characters")
        if (
            self.app_env.lower() not in {"local", "test"}
            and self.model_provider.lower() != "bedrock"
        ):
            raise ValueError("Deployed environments require MODEL_PROVIDER=bedrock")
        return self


settings = Settings()
