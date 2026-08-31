import json
import re
import threading
from collections.abc import Mapping
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any, Protocol

from app.core.config import Settings


class ModelGatewayError(RuntimeError):
    """Raised when a model cannot be invoked or returns an invalid response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "MODEL_GATEWAY_ERROR",
        component: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = (
            code
            if re.fullmatch(r"[A-Z0-9_-]{1,128}", code)
            else "MODEL_GATEWAY_ERROR"
        )
        self.component = (
            component
            if component and re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", component)
            else None
        )


def _bedrock_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error", {})
        if isinstance(error, Mapping):
            candidate = str(error.get("Code", ""))
            if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", candidate):
                return f"BEDROCK_{candidate.upper()}"
    return "BEDROCK_INVOCATION_FAILED"


class ModelGeneration(str):
    usage: dict[str, int]
    provider_metrics: dict[str, Any]

    def __new__(
        cls,
        text: str,
        *,
        usage: Mapping[str, int] | None = None,
        provider_metrics: Mapping[str, Any] | None = None,
    ):
        instance = super().__new__(cls, text)
        instance.usage = dict(usage or {})
        instance.provider_metrics = dict(provider_metrics or {})
        return instance


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
        self.settings = settings
        self.model_id = settings.model_id
        self.aws_region = settings.aws_region
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.aws_region,
                config=Config(
                    connect_timeout=self.settings.model_connect_timeout_seconds,
                    read_timeout=self.settings.model_read_timeout_seconds,
                    retries={"mode": "standard", "max_attempts": 3},
                ),
            )
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
            return ModelGeneration(
                "\n".join(text_blocks),
                usage=response.get("usage", {}),
                provider_metrics=response.get("metrics", {}),
            )
        except Exception as exc:
            raise ModelGatewayError(
                "The configured model could not produce a response.",
                code=_bedrock_error_code(exc),
                component="bedrock",
            ) from exc


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
        if prompt_id == "PROMPT_ID: dependency_planner":
            return json.dumps(self._dependency_plan(payload))
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
    def _dependency_plan(payload: Mapping[str, Any]) -> dict[str, Any]:
        missing_questions = list(payload.get("missing_input_questions", []))
        if missing_questions:
            return {
                "status": "needs_input",
                "requests": [],
                "questions": missing_questions,
                "reason_code": "MISSING_REQUIRED_INPUT",
            }
        allowed = list(payload.get("allowed_requests", []))
        if allowed:
            requests = [
                {
                    key: item[key]
                    for key in (
                        "capability",
                        "reason_code",
                        "required_output_fields",
                        "required",
                    )
                }
                for item in allowed
            ]
            return {
                "status": "needs_dependency",
                "requests": requests,
                "questions": [],
                "reason_code": "APPROVED_CAPABILITY_REQUIRED",
            }
        return {
            "status": "ready",
            "requests": [],
            "questions": [],
            "reason_code": None,
        }

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
                feasibility = grounding.get("feasibility", [])
                if feasibility:
                    first_feasibility = feasibility[0]
                    if first_feasibility["status"] == "shortfall":
                        summary += (
                            " This exceeds the estimated savings capacity by SGD "
                            f"{first_feasibility['monthly_shortfall']:.2f} per month."
                        )
                    else:
                        summary += " The estimated monthly savings capacity covers this amount."
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


_model_trace_id: ContextVar[str | None] = ContextVar("model_trace_id", default=None)


class TracingModelGateway:
    """Collects privacy-safe model telemetry while preserving the gateway contract."""

    def __init__(self, delegate: ModelGateway, settings: Settings) -> None:
        self.delegate = delegate
        self.settings = settings
        self._lock = threading.Lock()
        self._calls: dict[str, list[dict[str, Any]]] = {}
        self._closed: set[str] = set()

    def bind_trace(self, trace_id: str) -> Token:
        with self._lock:
            self._calls[trace_id] = []
            self._closed.discard(trace_id)
        return _model_trace_id.set(trace_id)

    @staticmethod
    def reset_trace(token: Token) -> None:
        _model_trace_id.reset(token)

    def snapshot(self, trace_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._calls.get(trace_id, [])]

    def clear(self, trace_id: str) -> None:
        with self._lock:
            self._calls.pop(trace_id, None)
            self._closed.add(trace_id)

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        trace_id = _model_trace_id.get()
        if trace_id:
            with self._lock:
                if len(self._calls.get(trace_id, [])) >= self.settings.max_model_calls_per_run:
                    raise ModelGatewayError("The workflow exceeded its model-call budget.")

        started = perf_counter()
        status = "completed"
        generation: str = ""
        error_code: str | None = None
        try:
            generation = self.delegate.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return generation
        except Exception as exc:
            status = "failed"
            error_code = type(exc).__name__
            raise
        finally:
            if trace_id:
                usage = getattr(generation, "usage", {})
                prompt_id = system_prompt.splitlines()[0].removeprefix("PROMPT_ID:").strip()
                call = {
                    "component": prompt_id or "unknown",
                    "status": status,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "input_characters": len(user_prompt),
                    "output_characters": len(generation),
                    "input_tokens": usage.get("inputTokens"),
                    "output_tokens": usage.get("outputTokens"),
                    "total_tokens": usage.get("totalTokens"),
                    "error_code": error_code,
                }
                with self._lock:
                    if trace_id in self._closed:
                        total_tokens = 0
                    else:
                        calls = self._calls.setdefault(trace_id, [])
                        calls.append(call)
                        total_tokens = sum(
                            int(item.get("total_tokens") or 0) for item in calls
                        )
                if total_tokens > self.settings.max_model_tokens_per_run and status == "completed":
                    raise ModelGatewayError(
                        "The workflow exceeded its model-token budget.",
                        code="MODEL_TOKEN_BUDGET_EXCEEDED",
                        component="model_budget",
                    )
