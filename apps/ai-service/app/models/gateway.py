import json
from collections.abc import Mapping
from typing import Any, Protocol

from app.core.config import Settings


class ModelGatewayError(RuntimeError):
    """Raised when a model cannot be invoked or returns an invalid response."""


class ModelGateway(Protocol):
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str: ...


class BedrockModelGateway:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.model_id = settings.model_id
        self.aws_region = settings.aws_region
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self.aws_region)
        return self._client

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            content = response["output"]["message"]["content"]
            text_blocks = [block["text"] for block in content if "text" in block]
            if not text_blocks:
                raise KeyError("response contained no text block")
            return "\n".join(text_blocks)
        except Exception as exc:
            raise ModelGatewayError("The configured model could not produce a response.") from exc


class LocalFixtureModelGateway:
    """Offline-only fixture for tests, evaluations, and local service wiring."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        del temperature, max_tokens
        payload = json.loads(user_prompt)
        prompt_id = system_prompt.splitlines()[0].strip()
        if prompt_id == "PROMPT_ID: router":
            return json.dumps(self._route(payload))
        if prompt_id.startswith("PROMPT_ID: agent_"):
            return json.dumps(self._specialist(prompt_id, payload))
        if prompt_id == "PROMPT_ID: synthesizer":
            summaries = [item["summary"] for item in payload["agent_results"]]
            return json.dumps({"answer": " ".join(summaries)})
        if prompt_id == "PROMPT_ID: risk_compliance":
            return json.dumps(
                {
                    "blocked": False,
                    "summary": "The response passed model-assisted compliance review.",
                    "rationale": ["No disallowed personalized investment instruction was found."],
                    "policy_notes": [],
                    "confidence": 0.91,
                }
            )
        raise ModelGatewayError(f"Unsupported local fixture prompt: {prompt_id}")

    @staticmethod
    def _route(payload: Mapping[str, Any]) -> dict[str, Any]:
        requested = payload.get("requested_agents")
        if requested:
            selected = list(requested)
        else:
            message = str(payload["message"]).lower()
            rules = {
                "spending": ["spend", "transaction", "expense", "anomaly", "dining"],
                "budget": ["budget", "allocate", "afford", "monthly"],
                "goal_strategy": ["goal", "save", "emergency fund", "vacation", "home"],
                "investment_education": ["invest", "etf", "diversification", "risk", "cpf"],
            }
            selected = [name for name, terms in rules.items() if any(term in message for term in terms)]
        return {
            "selected_agents": selected or ["budget"],
            "rationale": ["Offline fixture selected agents for repeatable integration testing."],
        }

    @staticmethod
    def _specialist(prompt_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        grounding = payload.get("grounding", {})
        if prompt_id.endswith("spending"):
            totals = grounding.get("category_totals", {})
            if totals:
                category = max(totals, key=totals.get)
                summary = f"Your highest spending category is {category} at SGD {totals[category]:.2f}."
            else:
                summary = "No recent transactions were provided."
        elif prompt_id.endswith("budget"):
            if grounding.get("income", 0) == 0:
                summary = "Add monthly income and recurring expenses to generate a personalized budget."
            else:
                summary = (
                    "After recurring expenses, estimated disposable income is SGD "
                    f"{grounding['disposable_income']:.2f}."
                )
        elif prompt_id.endswith("goal_strategy"):
            projections = grounding.get("projections", [])
            summary = "No goals were provided for projection."
            if projections:
                first = projections[0]
                summary = (
                    f"To reach {first['name']}, estimated monthly savings required are "
                    f"SGD {first['monthly_required']:.2f}."
                )
        else:
            summary = (
                "Investment education should focus on diversification, risk tolerance, time "
                "horizon, and fees without naming a product to buy."
            )
        return {
            "summary": summary,
            "rationale": ["The response is grounded in the supplied, allowlisted tool output."],
            "confidence": 0.8,
        }


def create_model_gateway(settings: Settings) -> ModelGateway:
    provider = settings.model_provider.lower()
    if provider == "bedrock":
        return BedrockModelGateway(settings)
    if provider == "local_fixture" and settings.app_env.lower() in {"local", "test"}:
        return LocalFixtureModelGateway()
    raise ValueError(f"Unsupported MODEL_PROVIDER for APP_ENV={settings.app_env}: {provider}")
