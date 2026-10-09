import json
import re
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.prompts import CURRENT_PROMPT_VERSION


class ModelRolePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    reasoning_effort: str | None = Field(
        default=None, pattern=r"^(none|low|medium|high|xhigh|max)$",
    )
    max_tokens: int | None = Field(default=None, ge=1, le=8192)


def default_model_role_policies() -> dict[str, ModelRolePolicy]:
    path = Path(__file__).with_name("model-role-policy.json")
    return {name: ModelRolePolicy.model_validate(policy)
            for name, policy in json.loads(path.read_text(encoding="utf-8")).items()}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        hide_input_in_errors=True,
        extra="ignore",  # Shared .env files also contain backend/frontend settings.
    )

    app_env: str = Field(default="local", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    model_provider: str = Field(default="openai", alias="MODEL_PROVIDER")
    model_id: str = Field(
        default="gpt-6-luna",
        alias="MODEL_ID",
    )
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    model_reasoning_effort: str = Field(default="medium", pattern=r"^(none|low|medium|high|xhigh|max)$", alias="MODEL_REASONING_EFFORT")
    model_role_overrides: dict[str, ModelRolePolicy] = Field(
        default_factory=default_model_role_policies, alias="MODEL_ROLE_OVERRIDES",
    )
    embedding_model_id: str = Field(
        default="cohere.embed-multilingual-v3",
        alias="EMBEDDING_MODEL_ID",
    )
    aws_region: str = Field(default="ap-southeast-1", alias="AWS_REGION")
    prompt_set_version: str = Field(
        default=CURRENT_PROMPT_VERSION,
        alias="PROMPT_SET_VERSION",
    )
    router_temperature: float = Field(default=0.2, ge=0.01, le=1.0, alias="ROUTER_TEMPERATURE")
    agent_temperature: float = Field(default=0.35, ge=0.01, le=1.0, alias="AGENT_TEMPERATURE")
    compliance_temperature: float = Field(
        default=0.1, ge=0.01, le=1.0, alias="COMPLIANCE_TEMPERATURE"
    )
    model_max_tokens: int = Field(default=3200, ge=100, le=4096, alias="MODEL_MAX_TOKENS")
    max_dependency_rounds: int = Field(
        default=6,
        ge=1,
        le=10,
        alias="MAX_DEPENDENCY_ROUNDS",
    )
    max_task_attempts: int = Field(default=3, ge=1, le=10, alias="MAX_TASK_ATTEMPTS")
    max_parallel_agents: int = Field(default=4, ge=1, le=8, alias="MAX_PARALLEL_AGENTS")
    agent_timeout_seconds: float = Field(
        default=45.0,
        gt=0,
        le=120,
        alias="AGENT_TIMEOUT_SECONDS",
    )
    build_commit: str = Field(default="unknown", pattern=r"^(unknown|[a-f0-9]{40})$", alias="BUILD_COMMIT")
    workflow_timeout_seconds: float = Field(default=85, gt=0, le=115, alias="WORKFLOW_TIMEOUT_SECONDS")
    review_diagnostics_dir: str | None = Field(default=None, alias="REVIEW_DIAGNOSTICS_DIR")
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
        default=80000,
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
        default=30.0,
        gt=0,
        le=120,
        alias="MODEL_READ_TIMEOUT_SECONDS",
    )
    vector_store_url: str = Field(default="http://localhost:6333", alias="VECTOR_STORE_URL")
    rag_provider: str = Field(default="local_fixture", alias="RAG_PROVIDER")
    rag_manifest_path: str | None = Field(default=None, alias="RAG_MANIFEST_PATH")
    rag_documents_path: str | None = Field(default=None, alias="RAG_DOCUMENTS_PATH")
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
    policy_rag_manifest_path: str | None = Field(default=None, alias="POLICY_RAG_MANIFEST_PATH")
    policy_rag_documents_path: str | None = Field(default=None, alias="POLICY_RAG_DOCUMENTS_PATH")
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

    def model_policy(self, component: str, max_tokens: int) -> ModelRolePolicy:
        override = self.model_role_overrides.get(component, ModelRolePolicy())
        return ModelRolePolicy(
            model_id=override.model_id or self.model_id,
            reasoning_effort=override.reasoning_effort or self.model_reasoning_effort,
            max_tokens=override.max_tokens or max_tokens,
        )

    @model_validator(mode="after")
    def require_deployment_api_key(self) -> Self:
        # Optional deployment assertion, never a selector for historical behavior.
        if self.prompt_set_version != CURRENT_PROMPT_VERSION:
            raise ValueError(f"The packaged application requires PROMPT_SET_VERSION={CURRENT_PROMPT_VERSION}")
        roles = {
            "router", "dependency_planner", "follow_up", "synthesizer", "risk_compliance",
            "agent_spending", "agent_budget", "agent_goal_strategy", "agent_investment_education",
            "goal_capture", "goal_input_requirements", "budget_capture", "budget_input_requirements", "spending_capture",
            "education_query_planner", "education_answerability",
            "response_composer", "action_grounding_review",
        }
        if set(self.model_role_overrides) - roles:
            raise ValueError("MODEL_ROLE_OVERRIDES contains an unknown model role")
        if self.app_env.lower() != "local" and (
            self.api_key == "change-me-locally" or len(self.api_key) < 20
        ):
            raise ValueError("AI_SERVICE_API_KEY must be a non-default value of at least 20 characters")
        if (
            self.model_provider.lower() == "openai"
            and self.app_env.lower() not in {"local", "test"}
            and (not self.openai_api_key or not self.openai_api_key.get_secret_value().strip())
        ):
            raise ValueError("OPENAI_API_KEY is required for the deployed OpenAI model")
        if self.app_env.lower() not in {"local", "test"} and self.model_provider.lower() != "openai":
            raise ValueError("Deployed environments require MODEL_PROVIDER=openai")
        if self.app_env.lower() not in {"local", "test"}:
            if self.rag_provider.lower() not in {"bedrock", "local_documents"}:
                raise ValueError("Deployed environments require governed Education retrieval")
            if self.rag_provider.lower() == "bedrock" and not re.fullmatch(
                r"[A-Za-z0-9]{10}", self.education_knowledge_base_id or "",
            ):
                raise ValueError("EDUCATION_KNOWLEDGE_BASE_ID must identify the deployed Bedrock KB")
            if self.education_corpus_version.endswith("@local-fixture-v1"):
                raise ValueError(
                    "EDUCATION_CORPUS_VERSION must identify the deployed governed corpus"
                )
            if self.policy_rag_provider.lower() not in {"bedrock", "local_documents"}:
                raise ValueError("Deployed environments require governed Policy retrieval")
            if self.policy_rag_provider.lower() == "bedrock" and not re.fullmatch(
                r"[A-Za-z0-9]{10}", self.policy_knowledge_base_id or "",
            ):
                raise ValueError("POLICY_KNOWLEDGE_BASE_ID must identify the deployed Bedrock KB")
            if self.policy_corpus_version.endswith("@local-fixture-v1"):
                raise ValueError(
                    "POLICY_CORPUS_VERSION must identify the deployed governed corpus"
                )
        return self


settings = Settings()
