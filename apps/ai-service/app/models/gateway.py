import json
import re
import threading
from collections.abc import Mapping
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from app.agents.education_access import education_gap_message, education_topics
from app.core.config import Settings
from app.core.run_trace import task_context
from app.core.telemetry import context_fields, log_event, trace_method


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

    @trace_method
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        try:
            log_event("bedrock.converse.request", model_id=self.model_id, provider="bedrock")
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
            )
            log_event(
                "bedrock.converse.response",
                status_code=response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                input_tokens=response.get("usage", {}).get("inputTokens"),
                output_tokens=response.get("usage", {}).get("outputTokens"),
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


class OpenAIModelGateway:
    """Text-only Responses API adapter for the existing typed agent contract."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self.settings = settings
        self.model_id = settings.model_id
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            key = self.settings.openai_api_key
            if not key or not key.get_secret_value().strip():
                raise ModelGatewayError(
                    "The OpenAI API key is not configured.",
                    code="OPENAI_API_KEY_MISSING",
                    component="openai",
                )
            self._client = OpenAI(
                api_key=key.get_secret_value(),
                timeout=self.settings.model_read_timeout_seconds,
                max_retries=0,
            )
        return self._client

    @trace_method
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        # GPT-6 reasoning requests do not accept temperature. Keep the argument
        # for the existing agent interface, but do not forward it to OpenAI.
        del temperature
        try:
            log_event("openai.responses.request", model_id=self.model_id, provider="openai")
            response = self.client.responses.create(
                model=self.model_id,
                instructions=system_prompt,
                input=[
                    {"role": "developer", "content": "Return one valid JSON object matching the required contract."},
                    {"role": "user", "content": user_prompt},
                ],
                reasoning={"effort": self.settings.model_reasoning_effort},
                max_output_tokens=max_tokens,
                text={"format": {"type": "json_object"}},
                store=False,
            )
            if response.status != "completed" or not response.output_text.strip():
                raise ValueError("incomplete or empty response")
            usage = response.usage
            input_tokens = int(usage.input_tokens) if usage else 0
            output_tokens = int(usage.output_tokens) if usage else 0
            log_event(
                "openai.responses.response",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return ModelGeneration(
                response.output_text,
                usage={
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "totalTokens": input_tokens + output_tokens,
                },
            )
        except ModelGatewayError:
            raise
        except Exception as exc:
            raise ModelGatewayError(
                "The configured model could not produce a response.",
                code=("OPENAI_RATE_LIMITED" if getattr(exc, "status_code", None) == 429
                      else "OPENAI_INVOCATION_FAILED"),
                component="openai",
            ) from exc


class LocalFixtureModelGateway:
    """Offline-only fixture for tests, evaluations, and local service wiring."""

    @trace_method
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
            uncertainties = list(
                dict.fromkeys(
                    uncertainty
                    for item in payload["agent_results"]
                    for uncertainty in item.get("uncertainties", [])
                )
            )
            answer = " ".join(summaries)
            if uncertainties:
                answer = f"{answer} Uncertainty: {' '.join(uncertainties)}"
            return json.dumps({"answer": answer})
        if prompt_id == "PROMPT_ID: risk_compliance":
            return json.dumps(
                {
                    "blocked": False,
                    "summary": "The response passed model-assisted compliance review.",
                    "rationale": ["No disallowed personalized investment instruction was found."],
                    "policy_notes": [],
                    "request_allowed": True,
                    "complete": True,
                    "missing_points": [],
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
                "investment_education": [
                    "invest", "etf", "diversification", "risk", "cpf", "bond", "shares",
                    "stock", "reit", "unit trust", "mutual fund",
                ],
            }
            selected = [name for name, terms in rules.items() if any(term in message for term in terms)]
            topics = education_topics(str(payload["message"]))
            if topics and "investment_education" not in selected and not (
                topics == ["emergency fund readiness"] and "goal_strategy" in selected
            ):
                selected.append("investment_education")
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
            contexts = grounding.get("contexts", [])
            summary = (
                str(contexts[0]["text"])
                if contexts
                else "Approved investment-education evidence was unavailable."
            )
            if not contexts and grounding.get("fallback_topics"):
                # The offline fixture cannot supply model knowledge; abstain honestly.
                summary = ""
            if contexts and grounding.get("response_language") == "Chinese":
                translations = {
                    "cpf-beginners-guide-to-investing": (
                        "投资需考虑期限、风险承受能力、费用和分散投资，投资可能亏损。"
                        "国库券以低于面值的价格发行，到期按面值偿还；新加坡储蓄债券由政府发行。"
                    ),
                    "cpf-investment-scheme-guide": (
                        "公积金投资计划提供不同风险与回报的投资选择。需了解目标、期限、"
                        "风险承受能力、分散投资和费用；公积金局不为特定投资产品背书。"
                    ),
                    "moneysense-what-is-investing": (
                        "开始投资前应了解准备条件、风险与回报和投资期限。投资可能亏损，回报并不确定。"
                    ),
                    "moneysense-managing-investment-risk": (
                        "投资风险包括市场、信用、流动性和汇率风险。分散投资可减少集中风险，"
                        "但无法消除亏损。定投是在固定时间间隔投入固定金额，不随市场涨跌改变。"
                    ),
                    "moneysense-types-of-investments": (
                        "股票、债券、基金、交易所交易基金和房地产投资信托是不同投资类别，"
                        "其结构、风险、流动性、费用和潜在回报不同。"
                    ),
                    "moneysense-guide-to-etfs": (
                        "了解交易所交易基金时，应关注费用、流动性、跟踪误差和交易对手风险。"
                        "基金价值可能下降，回报并不确定。"
                    ),
                }
                summary = translations.get(contexts[0]["source_id"], summary)
            if grounding.get("source_verification"):
                summary = "Sources available for this answer:\n" + "\n".join(
                    f"- {source['issuing_organization']}: {source['title']}; "
                    f"document date {source['published_at']}, version {source['document_version']}. "
                    f"[source:{source['source_id']}]"
                    for source in grounding.get("sources", [])
                ) + (
                    "\nThese are captured document dates, not live checks of current rates "
                    "or provider status. A review deadline does not establish current accuracy."
                )
        response = {
            "summary": summary,
            "rationale": ["The response is grounded in the supplied, allowlisted tool output."],
            "confidence": 0.8,
        }
        if prompt_id.endswith("investment_education"):
            response.update(
                {
                    "source_ids": [
                        source["source_id"]
                        for source in grounding.get("sources", [])
                    ],
                    "uncertainties": [
                        "Investment outcomes vary and losses are possible."
                        if grounding.get("contexts") else education_gap_message(grounding)
                    ],
                }
            )
        return response


def create_model_gateway(settings: Settings) -> ModelGateway:
    provider = settings.model_provider.lower()
    if provider == "openai":
        return OpenAIModelGateway(settings)
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

    def bind_trace(self, trace_id: str) -> Token:
        with self._lock:
            self._calls[trace_id] = []
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

    @trace_method
    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        trace_id = _model_trace_id.get()
        call_id = str(uuid4())
        started = perf_counter()
        component = system_prompt.splitlines()[0].removeprefix("PROMPT_ID:").strip()
        log_event(
            "model.generation.started",
            call_id=call_id,
            trace_id=trace_id,
            component=component,
            provider=self.settings.model_provider,
            model_id=self.settings.model_id,
            input_characters=len(user_prompt),
        )
        if trace_id:
            with self._lock:
                calls = self._calls.get(trace_id)
                if calls is None:
                    raise ModelGatewayError(
                        "The workflow has already closed.",
                        code="WORKFLOW_CLOSED", component="model_budget",
                    )
                if len(calls) >= self.settings.max_model_calls_per_run:
                    raise ModelGatewayError("The workflow exceeded its model-call budget.")
                if sum(int(item.get("total_tokens") or 0) for item in calls) >= self.settings.max_model_tokens_per_run:
                    raise ModelGatewayError(
                        "The workflow exceeded its model-token budget.",
                        code="MODEL_TOKEN_BUDGET_EXCEEDED", component="model_budget",
                    )
                call = {
                    "call_id": call_id,
                    "trace_id": trace_id,
                    "span_id": context_fields().get("span_id"),
                    **(task_context.get() or {}),
                    "component": system_prompt.splitlines()[0].removeprefix("PROMPT_ID:").strip() or "unknown",
                    "status": "running",
                    "duration_ms": 0.0,
                    "input_characters": len(user_prompt),
                    "output_characters": 0,
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                    "error_code": None,
                }
                calls.append(call)

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
            usage = getattr(generation, "usage", {})
            log_event(
                "model.generation.finished",
                call_id=call_id,
                trace_id=trace_id,
                component=component,
                status=status,
                output_characters=len(generation),
                input_tokens=usage.get("inputTokens"),
                output_tokens=usage.get("outputTokens"),
                duration_ms=round((perf_counter() - started) * 1000, 2),
                error_code=error_code,
            )
            if trace_id:
                usage = getattr(generation, "usage", {})
                completed = {
                    "status": status,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                    "output_characters": len(generation),
                    "input_tokens": usage.get("inputTokens"),
                    "output_tokens": usage.get("outputTokens"),
                    "total_tokens": usage.get("totalTokens"),
                    "error_code": error_code,
                }
                with self._lock:
                    if self._calls.get(trace_id) is not calls:
                        total_tokens = 0
                    else:
                        call.update(completed)
                        total_tokens = sum(
                            int(item.get("total_tokens") or 0) for item in calls
                        )
                if total_tokens > self.settings.max_model_tokens_per_run and status == "completed":
                    raise ModelGatewayError(
                        "The workflow exceeded its model-token budget.",
                        code="MODEL_TOKEN_BUDGET_EXCEEDED",
                        component="model_budget",
                    )
