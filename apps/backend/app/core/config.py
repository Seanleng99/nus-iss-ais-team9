from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings
from sqlalchemy import URL

from app.core.data_lifecycle import DATA_LIFECYCLE_POLICY


class Settings(BaseSettings):
    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    api_key: str = Field(default="change-me-locally", alias="BACKEND_API_KEY")
    automation_api_key_enabled: bool = Field(
        default=True, alias="AUTOMATION_API_KEY_ENABLED"
    )
    automation_user_id_prefixes: str = Field(
        default="deployment-,live-evaluation,load-test-user-",
        alias="AUTOMATION_USER_ID_PREFIXES",
    )
    oidc_auth_enabled: bool = Field(default=False, alias="OIDC_AUTH_ENABLED")
    oidc_metadata_proxy_enabled: bool = Field(
        default=False, alias="OIDC_METADATA_PROXY_ENABLED"
    )
    oidc_issuer_url: str | None = Field(default=None, alias="OIDC_ISSUER_URL")
    oidc_jwks_url: str | None = Field(default=None, alias="OIDC_JWKS_URL")
    oidc_client_id: str | None = Field(default=None, alias="OIDC_CLIENT_ID")
    oidc_legacy_issuer_url: str | None = Field(
        default=None, alias="OIDC_LEGACY_ISSUER_URL"
    )
    oidc_server_metadata_url: str | None = Field(
        default=None, alias="OIDC_SERVER_METADATA_URL"
    )
    frontend_url: str | None = Field(default=None, alias="FRONTEND_URL")
    oidc_required_token_use: str | None = Field(
        default=None, alias="OIDC_REQUIRED_TOKEN_USE"
    )
    oidc_clock_skew_seconds: int = Field(
        default=30, ge=0, le=300, alias="OIDC_CLOCK_SKEW_SECONDS"
    )
    ai_service_base_url: str = Field(
        default="http://localhost:8001", alias="AI_SERVICE_BASE_URL"
    )
    ai_service_api_key: str = Field(
        default="change-me-locally", alias="AI_SERVICE_API_KEY"
    )
    ai_service_timeout_seconds: float = Field(
        default=90.0, gt=0, le=120, alias="AI_SERVICE_TIMEOUT_SECONDS"
    )
    ai_service_composition_timeout_seconds: float = Field(
        default=25.0, gt=0, le=120, alias="AI_SERVICE_COMPOSITION_TIMEOUT_SECONDS"
    )
    trace_retention_days: int = Field(
        default=30, ge=1, le=365, alias="TRACE_RETENTION_DAYS"
    )
    chat_retention_days: int = Field(
        default=90, ge=1, le=730, alias="CHAT_RETENTION_DAYS"
    )
    synthetic_user_retention_days: int = Field(
        default=30, ge=1, le=365, alias="SYNTHETIC_USER_RETENTION_DAYS"
    )
    durable_agent_memory_enabled: bool = Field(
        default=False, alias="DURABLE_AGENT_MEMORY_ENABLED"
    )
    postgres_url: str | None = Field(default=None, alias="POSTGRES_URL")
    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, ge=1, le=65535, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="financial_wellness", alias="POSTGRES_DB")
    postgres_user: str = Field(default="coach", alias="POSTGRES_USER")
    postgres_password: str = Field(default="coach", alias="POSTGRES_PASSWORD")
    postgres_sslmode: str = Field(default="prefer", alias="POSTGRES_SSLMODE")
    postgres_secret_arn: str | None = Field(default=None, alias="POSTGRES_SECRET_ARN")
    aws_region: str | None = Field(default=None, alias="AWS_REGION")

    @model_validator(mode="after")
    def require_host_for_postgres_secret(self) -> Self:
        if self.postgres_secret_arn is not None:
            if not self.postgres_secret_arn.strip():
                raise ValueError("POSTGRES_SECRET_ARN must not be blank")
            if not self.postgres_host or not self.postgres_host.strip():
                raise ValueError("POSTGRES_HOST is required with POSTGRES_SECRET_ARN")
        return self

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

    @property
    def automation_user_id_prefix_list(self) -> tuple[str, ...]:
        return tuple(
            prefix.strip()
            for prefix in self.automation_user_id_prefixes.split(",")
            if prefix.strip()
        )

    @model_validator(mode="after")
    def require_deployment_secrets(self) -> Self:
        policy_retention = DATA_LIFECYCLE_POLICY["retention"]
        configured_retention = {
            "TRACE_RETENTION_DAYS": (
                self.trace_retention_days,
                policy_retention["orchestration_traces_days"],
            ),
            "CHAT_RETENTION_DAYS": (
                self.chat_retention_days,
                policy_retention["chat_history_days"],
            ),
            "SYNTHETIC_USER_RETENTION_DAYS": (
                self.synthetic_user_retention_days,
                policy_retention["synthetic_automation_users_days"],
            ),
        }
        extended = [
            name
            for name, (configured, maximum) in configured_retention.items()
            if configured > maximum
        ]
        if extended:
            raise ValueError(
                f"{', '.join(extended)} cannot extend data lifecycle policy retention"
            )
        if self.durable_agent_memory_enabled and not DATA_LIFECYCLE_POLICY["consent"][
            "durable_agent_memory"
        ]["feature_enabled"]:
            raise ValueError(
                "DURABLE_AGENT_MEMORY_ENABLED cannot override the disabled lifecycle policy"
            )
        if self.app_env.lower() != "local":
            service_secrets = []
            if self.automation_api_key_enabled:
                service_secrets.append(("BACKEND_API_KEY", self.api_key))
                if not self.automation_user_id_prefix_list:
                    raise ValueError("AUTOMATION_USER_ID_PREFIXES must not be empty")
            service_secrets.append(("AI_SERVICE_API_KEY", self.ai_service_api_key))
            invalid = [
                name
                for name, value in service_secrets
                if value == "change-me-locally" or len(value) < 20
            ]
            if invalid:
                raise ValueError(
                    f"{', '.join(invalid)} must be non-default values of at least 20 characters"
                )
            if self.postgres_sslmode not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("POSTGRES_SSLMODE must require TLS outside local development")
            if self.oidc_auth_enabled:
                oidc_values = {
                    "OIDC_ISSUER_URL": self.oidc_issuer_url,
                    "OIDC_JWKS_URL": self.oidc_jwks_url,
                    "OIDC_CLIENT_ID": self.oidc_client_id,
                }
                missing_oidc = [name for name, value in oidc_values.items() if not value]
                if missing_oidc:
                    raise ValueError(f"{', '.join(missing_oidc)} must be configured")
                insecure_urls = [
                    name
                    for name in ("OIDC_ISSUER_URL", "OIDC_JWKS_URL")
                    if not str(oidc_values[name]).startswith("https://")
                ]
                if insecure_urls:
                    raise ValueError(f"{', '.join(insecure_urls)} must use HTTPS")
                if self.oidc_required_token_use != "id":
                    raise ValueError("OIDC_REQUIRED_TOKEN_USE must be id")
            if self.oidc_metadata_proxy_enabled:
                if not self.oidc_auth_enabled:
                    raise ValueError(
                        "OIDC_METADATA_PROXY_ENABLED requires OIDC_AUTH_ENABLED"
                    )
                metadata_values = {
                    "OIDC_SERVER_METADATA_URL": self.oidc_server_metadata_url,
                    "FRONTEND_URL": self.frontend_url,
                }
                missing_metadata = [
                    name for name, value in metadata_values.items() if not value
                ]
                if missing_metadata:
                    raise ValueError(f"{', '.join(missing_metadata)} must be configured")
                insecure_metadata = [
                    name
                    for name, value in metadata_values.items()
                    if not str(value).startswith("https://")
                ]
                if insecure_metadata:
                    raise ValueError(f"{', '.join(insecure_metadata)} must use HTTPS")
        return self


settings = Settings()
