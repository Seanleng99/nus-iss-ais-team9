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
        default="cohere.embed-multilingual-v3",
        alias="EMBEDDING_MODEL_ID",
    )
    aws_region: str = Field(default="ap-southeast-1", alias="AWS_REGION")
    prompt_set_version: str = Field(
        default="v5",
        pattern=r"^v(?:2|3|4|5)$",
        alias="PROMPT_SET_VERSION",
    )
    router_temperature: float = Field(default=0.2, ge=0.01, le=1.0, alias="ROUTER_TEMPERATURE")
    agent_temperature: float = Field(default=0.35, ge=0.01, le=1.0, alias="AGENT_TEMPERATURE")
    compliance_temperature: float = Field(
        default=0.1, ge=0.01, le=1.0, alias="COMPLIANCE_TEMPERATURE"
    )
    model_max_tokens: int = Field(default=800, ge=100, le=4096, alias="MODEL_MAX_TOKENS")
    max_dependency_rounds: int = Field(
        default=6,
        ge=1,
        le=10,
        alias="MAX_DEPENDENCY_ROUNDS",
    )
    max_task_attempts: int = Field(default=3, ge=1, le=10, alias="MAX_TASK_ATTEMPTS")
    max_parallel_agents: int = Field(default=4, ge=1, le=8, alias="MAX_PARALLEL_AGENTS")
    agent_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        le=120,
        alias="AGENT_TIMEOUT_SECONDS",
    )
    retry_backoff_seconds: float = Field(
        default=0.25,
        ge=0,
        le=10,
        alias="RETRY_BACKOFF_SECONDS",
    )
    max_model_calls_per_run: int = Field(
        default=20,
        ge=1,
        le=100,
        alias="MAX_MODEL_CALLS_PER_RUN",
    )
    max_model_tokens_per_run: int = Field(
        default=20000,
        ge=100,
        le=200000,
        alias="MAX_MODEL_TOKENS_PER_RUN",
    )
    model_connect_timeout_seconds: float = Field(
        default=3.0,
        gt=0,
        le=30,
        alias="MODEL_CONNECT_TIMEOUT_SECONDS",
    )
    model_read_timeout_seconds: float = Field(
        default=15.0,
        gt=0,
        le=120,
        alias="MODEL_READ_TIMEOUT_SECONDS",
    )
    vector_store_url: str = Field(default="http://localhost:6333", alias="VECTOR_STORE_URL")
    rag_provider: str = Field(default="local_fixture", alias="RAG_PROVIDER")
    education_knowledge_base_id: str | None = Field(
        default=None,
        alias="EDUCATION_KNOWLEDGE_BASE_ID",
    )
    education_corpus_version: str = Field(
        default="investment-education-sg@local-fixture-v1",
        pattern=r"^[a-z0-9][a-z0-9@._-]{2,127}$",
        alias="EDUCATION_CORPUS_VERSION",
    )
    rag_minimum_score: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        alias="RAG_MINIMUM_SCORE",
    )
    policy_rag_provider: str = Field(
        default="local_fixture",
        alias="POLICY_RAG_PROVIDER",
    )
    policy_knowledge_base_id: str | None = Field(
        default=None,
        alias="POLICY_KNOWLEDGE_BASE_ID",
    )
    policy_corpus_version: str = Field(
        default="financial-coach-policy-sg@local-fixture-v1",
        pattern=r"^[a-z0-9][a-z0-9@._-]{2,127}$",
        alias="POLICY_CORPUS_VERSION",
    )
    policy_rag_minimum_score: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        alias="POLICY_RAG_MINIMUM_SCORE",
    )
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
        if self.app_env.lower() not in {"local", "test"}:
            if self.rag_provider.lower() != "bedrock":
                raise ValueError("Deployed environments require RAG_PROVIDER=bedrock")
            if not self.education_knowledge_base_id:
                raise ValueError(
                    "EDUCATION_KNOWLEDGE_BASE_ID is required in deployed environments"
                )
            if self.education_corpus_version.endswith("@local-fixture-v1"):
                raise ValueError(
                    "EDUCATION_CORPUS_VERSION must identify the deployed governed corpus"
                )
            if self.policy_rag_provider.lower() != "bedrock":
                raise ValueError("Deployed environments require POLICY_RAG_PROVIDER=bedrock")
            if not self.policy_knowledge_base_id:
                raise ValueError(
                    "POLICY_KNOWLEDGE_BASE_ID is required in deployed environments"
                )
            if self.policy_corpus_version.endswith("@local-fixture-v1"):
                raise ValueError(
                    "POLICY_CORPUS_VERSION must identify the deployed governed corpus"
                )
        return self


settings = Settings()
