import json
import re
import threading
from collections.abc import Mapping
from contextvars import ContextVar, Token
from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

from coach_i18n import input_pattern, load_data, translate

from app.agents.education_access import education_gap_message, education_topics
from app.core.config import Settings
from app.core.run_trace import task_context
from app.core.telemetry import context_fields, log_event, trace_method
from app.models.contracts import output_format


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
    def __init__(self, settings: Settings, client: Any | None = None, *, total_max_attempts: int = 4) -> None:
        self.settings = settings
        self.model_id = settings.model_id
        self.aws_region = settings.aws_region
        self._client = client
        self._total_max_attempts = total_max_attempts

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
                    retries={"mode": "standard", "total_max_attempts": self._total_max_attempts},
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
        component = system_prompt.splitlines()[0].removeprefix("PROMPT_ID:").strip()
        policy = self.settings.model_policy(component, max_tokens)
        try:
            log_event("bedrock.converse.request", model_id=policy.model_id, provider="bedrock")
            response = self.client.converse(
                modelId=policy.model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                inferenceConfig={"maxTokens": policy.max_tokens, "temperature": temperature},
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
            from httpx import Timeout
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
                timeout=Timeout(
                    self.settings.model_read_timeout_seconds,
                    connect=self.settings.model_connect_timeout_seconds,
                ),
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
        component = system_prompt.splitlines()[0].removeprefix("PROMPT_ID:").strip()
        policy = self.settings.model_policy(component, max_tokens)
        try:
            log_event(
                "openai.responses.request", model_id=policy.model_id, provider="openai",
                reasoning_effort=policy.reasoning_effort, max_output_tokens=policy.max_tokens,
                temperature_supported=False,
            )
            response = self.client.responses.create(
                model=policy.model_id,
                instructions=system_prompt,
                input=[
                    {"role": "developer", "content": "Return one valid JSON object matching the required contract."},
                    {"role": "user", "content": user_prompt},
                ],
                reasoning={"effort": policy.reasoning_effort},
                max_output_tokens=policy.max_tokens,
                text={"format": output_format()},
                store=False,
            )
            if response.status == "incomplete":
                reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
                raise ModelGatewayError(
                    "The model response could not be completed.",
                    code=("MODEL_OUTPUT_TOKEN_LIMIT" if reason == "max_output_tokens"
                          else "MODEL_CONTENT_FILTERED" if reason == "content_filter"
                          else "MODEL_RESPONSE_INCOMPLETE"),
                    component=component or "openai",
                )
            if any(
                getattr(content, "type", None) == "refusal"
                for item in getattr(response, "output", [])
                for content in getattr(item, "content", [])
            ):
                raise ModelGatewayError(
                    "The model declined this request.", code="MODEL_REFUSAL",
                    component=component or "openai",
                )
            if response.status != "completed" or not response.output_text.strip():
                raise ModelGatewayError(
                    "The model returned no completed answer.", code="MODEL_RESPONSE_EMPTY",
                    component=component or "openai",
                )
            usage = response.usage
            input_tokens = int(usage.input_tokens) if usage else 0
            output_tokens = int(usage.output_tokens) if usage else 0
            reasoning_tokens = int(getattr(
                getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0,
            ) or 0)
            log_event(
                "openai.responses.response",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                reasoning_tokens=reasoning_tokens,
            )
            return ModelGeneration(
                response.output_text,
                usage={
                    "inputTokens": input_tokens,
                    "outputTokens": output_tokens,
                    "totalTokens": input_tokens + output_tokens,
                },
                provider_metrics={"reasoningTokens": reasoning_tokens},
            )
        except ModelGatewayError:
            raise
        except Exception as exc:  # noqa: BLE001 - adapter must hide even unexpected provider failures
            # SDK exceptions expose typed status/code metadata. Never read or
            # print their message, body, request headers, URL or API key.
            supplied_status = getattr(exc, "status_code", None)
            status = supplied_status if isinstance(supplied_status, int) else None
            error_class = type(exc).__name__
            supplied_code = getattr(exc, "code", None)
            safe_code = supplied_code if isinstance(supplied_code, str) else None
            if status == 401 or error_class in {"AuthenticationError", "OAuthError"} or safe_code == "invalid_api_key":
                code = "OPENAI_AUTHENTICATION_FAILED"
            elif status == 403 or error_class == "PermissionDeniedError" or safe_code in {"permission_denied", "model_access_denied"}:
                code = "OPENAI_ACCESS_DENIED"
            elif status == 404 or error_class == "NotFoundError" or safe_code in {"model_not_found", "unsupported_model"}:
                code = "OPENAI_MODEL_UNAVAILABLE"
            elif safe_code in {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active"}:
                code = "OPENAI_QUOTA_EXCEEDED"
            elif status == 429 or error_class == "RateLimitError":
                code = "OPENAI_RATE_LIMITED"
            elif status == 408 or error_class in {
                "APITimeoutError", "TimeoutException", "ReadTimeout", "ConnectTimeout",
                "WriteTimeout", "PoolTimeout",
            }:
                code = "OPENAI_TIMEOUT"
            elif error_class in {
                "APIConnectionError", "ConnectError", "NetworkError", "ReadError", "WriteError",
                "RemoteProtocolError", "ProxyError",
            }:
                code = "OPENAI_CONNECTION_ERROR"
            elif (isinstance(status, int) and 500 <= status <= 599) or error_class == "InternalServerError":
                code = "OPENAI_SERVER_ERROR"
            elif status in {400, 422} or error_class in {"BadRequestError", "UnprocessableEntityError"}:
                code = "OPENAI_INVALID_REQUEST"
            else:
                code = "OPENAI_INVOCATION_FAILED"
            raise ModelGatewayError(
                "The configured model could not produce a response.",
                code=code,
                component="openai",
            ) from None


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
        if prompt_id == "PROMPT_ID: goal_capture":
            from app.models.goal_fixture import fixture_goal_draft
            return json.dumps(fixture_goal_draft(payload))
        if prompt_id == "PROMPT_ID: budget_capture":
            from app.models.budget_fixture import fixture_budget_draft
            return json.dumps(fixture_budget_draft(payload))
        if prompt_id == "PROMPT_ID: spending_capture":
            from app.models.recurring_fixture import apply_recurring_terms
            from app.models.spending_fixture import fixture_spending_draft
            return json.dumps(apply_recurring_terms(payload, fixture_spending_draft(payload)))
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
                    "financial_language_safe": not bool(
                        payload.get("contextual_financial_findings")
                    ),
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
        context = payload.get("session_context", {})
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
            context = payload.get("session_context", {})
            if not selected and context.get("active_topic") in rules and re.fullmatch(
                r"(?:explain that(?: more simply)?|what about that|actually[, ]+(?:it(?:'s| is) )?[\d.,$ ]+|[\d.,$ ]+)[?.!]*",
                message,
            ):
                selected = [context["active_topic"]]
            topics = education_topics(str(payload["message"]))
            if topics and "investment_education" not in selected and not (
                topics == ["emergency fund readiness"] and "goal_strategy" in selected
            ):
                selected.append("investment_education")
        from app.agents.goal_capture import goal_change_request
        from app.agents.spending_capture import spending_capture_request
        message_text = str(payload["message"])
        # These recognizers are confined to the deterministic offline fixture.
        # Production routing remains the model's typed semantic decision.
        new_question = bool(re.search(
            r"\b(?:explain|teach|why|how|what|compare|tell me|should|look up)\b|[?]",
            message_text, re.IGNORECASE,
        ))
        detail_reply = bool(re.fullmatch(
            r"\s*(?:(?:name|goal_name|target_amount|current_amount|target_months|amount|"
            r"description|category|occurred_on|period_start|currency|income|savings)\s*:\s*[^?]+|"
            r"(?:SGD|S\$|\$)?\s*\d[\d., /-]*(?:months?)?)\s*", message_text, re.IGNORECASE,
        ))
        date_reply = bool(re.fullmatch(
            r"\s*(?:today|yesterday|tonight|this morning|"
            r"(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+20\d{2}|"
            r"20\d{2}-\d{1,2}(?:-\d{1,2})?|\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*[.!]?\s*",
            message_text, re.IGNORECASE,
        ))
        pending_budget = payload.get("pending_budget") or {}
        planning_reply = bool(pending_budget.get("planning")) and bool(re.fullmatch(
            r"\s*(?:all expenses included|use recorded spending|50/30/20|80/20|"
            r"zero-based|savings first|flexible method)\s*[.!]?\s*",
            message_text, re.IGNORECASE,
        ))
        budget_reply = bool(pending_budget) and not new_question and (
            detail_reply or date_reply or planning_reply
        )
        transaction_reply = bool(payload.get("pending_transaction")) and not new_question and (
            detail_reply or date_reply
        )
        goal_reply = bool(payload.get("pending_goal")) and detail_reply and not new_question
        if sum(bool(payload.get(field)) for field in (
            "pending_goal", "pending_budget", "pending_transaction",
        )) > 1 and re.fullmatch(r"\s*(?:SGD|S\$|\$)?\s*\d[\d.,]*\s*", message_text):
            # A bare number cannot choose among multiple pending operations.
            budget_reply = transaction_reply = goal_reply = False
        if budget_reply:
            selected = ["budget"]
        goal_capture = goal_change_request(message_text) or goal_reply
        if goal_capture and "goal_strategy" not in selected:
            selected.append("goal_strategy")
        spending_capture = transaction_reply or (
            not bool(payload.get("pending_budget"))
            and spending_capture_request(str(payload["message"]))
        )
        spending_capture = spending_capture or bool(
            re.search(r"\b(?:forecast|project|estimate|upcoming)\b", message_text, re.IGNORECASE)
            and re.search(r"\b(?:recurring|bills?|expenses?)\b", message_text, re.IGNORECASE)
        )
        if spending_capture:
            selected = list(dict.fromkeys(["spending", *selected])) if not transaction_reply else ["spending"]
            if any(term in str(payload["message"]).lower() for term in ("budget", "allocate")):
                selected.append("budget")
        budget_status = bool(re.search(
            r"\b(?:over(?: my| the)? budget|overspend\w*|exceed\w*.*(?:budget|income|limits?)|"
            r"(?:budget|spending).*on track|on track.*(?:budget|spending)|"
            r"how am I doing.*(?:budget|spending)|spending.*(?:okay|too high|under control))\b",
            message_text, re.IGNORECASE,
        )) or bool(context.get("pending_action") == "budget_status" and date_reply)
        if budget_status and "budget" not in selected:
            selected.append("budget")
        memory_question = bool(re.fullmatch(
            input_pattern("backend.services.session_context.recall_question"), message_text, re.IGNORECASE
        )) or bool(re.fullmatch(r"what did I tell you about (?:my )?income\??", message_text, re.IGNORECASE))
        memory_fields = ["monthly_income"] if memory_question and re.search(r"\bincome\b", message_text, re.IGNORECASE) else []
        return {
            "selected_agents": selected or ["budget"],
            "rationale": ["Offline fixture selected agents for repeatable integration testing."],
            "spending_capture": spending_capture,
            "goal_capture": goal_capture,
            "budget_status_query": budget_status,
            "memory_question": memory_question,
            "memory_fields": memory_fields,
            "budget_planning": bool(budget_reply and pending_budget.get("planning")) or (
                "budget" in str(payload["message"]).lower()
                and any(word in str(payload["message"]).lower()
                        for word in ("realistic", "category-level", "propose spending limits", "check my budget plan", "50/30/20", "80/20", "zero-based", "savings first", "custom percentages", "scenario", "what if", "compare", "review", "pace", "adjustment", "funded alternatives", "multi-month", "carry forward", "rollover", "periodic"))
            ),
            "budget_capture": budget_reply or (
                "budget" in str(payload["message"]).lower()
                and any(word in str(payload["message"]).lower().split()
                        for word in ("set", "save", "add", "update", "record", "change"))
            ),
        }

    @staticmethod
    def _spending_summary(payload: Mapping[str, Any], grounding: Mapping[str, Any]) -> str:
        try:
            inner = json.loads(str(payload.get("message", "")))
            question = str(inner.get("user_request", "")) if isinstance(inner, dict) else ""
        except (ValueError, TypeError):
            question = str(payload.get("message", ""))
        asked = question.lower()
        totals = grounding.get("category_totals", {})
        anomalies = list(grounding.get("anomalies", []))
        trends = list(grounding.get("category_trends", []))

        def label(category: str) -> str:
            return str(category).replace("_", " ").strip()

        def mentioned(category: str) -> bool:
            word = label(category).lower()
            return bool(word) and word in asked

        def anomaly_line(anomaly: Mapping[str, Any]) -> str:
            category = label(anomaly.get("category", "other"))
            if anomaly.get("aggregation") == "category_month_total":
                return (
                    f"Your recorded {category} category total is SGD {float(anomaly.get('amount', 0)):.2f} "
                    f"for {str(anomaly.get('occurred_on', 'the selected month'))[:7]}, compared with "
                    f"a recorded monthly comparison baseline of SGD {float(anomaly.get('expected_amount', 0)):.2f}."
                )
            return (
                f"I found the unusual {category} expense you noticed: SGD "
                f"{float(anomaly.get('amount', 0)):.2f} on {anomaly.get('occurred_on', 'a recent day')}, "
                f"about {abs(float(anomaly.get('deviation_percent', 0))):.0f}% above your usual "
                f"SGD {float(anomaly.get('expected_amount', 0)):.2f}."
            )

        def trend_line(trend: Mapping[str, Any]) -> str:
            category = label(trend.get("category", "other"))
            total = (
                f" Your {category} total is SGD {float(totals[category]):.2f}."
                if category in totals
                else ""
            )
            percent = trend.get("change_percent")
            comparison = f"({float(percent):+.1f}%)" if percent is not None else "(no comparable prior total)"
            return (
                f"Your {category} spending is SGD {float(trend.get('current_amount', 0)):.2f} this "
                f"month versus SGD {float(trend.get('previous_amount', 0)):.2f} last month "
                f"{comparison}.{total}"
            )

        def total_line(category: str) -> str:
            return f"Your {label(category)} total is SGD {float(totals[category]):.2f}."

        def reduction_note() -> str:
            return (
                "To reduce surprises like this, check whether it was a one-off booking or a "
                "new recurring cost, and set a category budget so future spikes get flagged early."
            )

        def quoted_anomaly() -> tuple[str, str, str] | None:
            # Insight cards embed the numbers, e.g. "A 5698.50 food expense is
            # 1601% higher than your historical average of 335.00".
            match = re.search(
                r"([\d,]+(?:\.\d{1,2})?)\s+([a-z][a-z _-]{1,30}?)\s+expense is\s*"
                r"(\d+(?:\.\d+)?)%\s+higher than your historical average of\s*([\d,]+(?:\.\d{1,2})?)",
                question,
                re.IGNORECASE,
            )
            if match is None:
                return None
            amount, category, percent, average = match.groups()
            return category.strip().lower(), percent, (
                f"I found the unusual {category.strip().lower()} expense you noticed: SGD "
                f"{float(amount.replace(',', '')):.2f} recently, about {percent}% above your usual "
                f"SGD {float(average.replace(',', '')):.2f}."
            )

        wants_reduction = any(word in asked for word in ("reduce", "cut", "lower", "save", "unexpected"))
        anomaly_asked = any(word in asked for word in ("unusual", "anomal", "unexpected", "spike"))

        # An insight-card question quotes the detector's exact numbers, so answer
        # with them for the quoted category; the backend may flag categories the
        # agent-side grounding does not carry.
        quoted = quoted_anomaly()
        if quoted is not None:
            quoted_category, _, quoted_line = quoted
            grounded = next(
                (a for a in anomalies if str(a.get("category")).lower() == quoted_category),
                None,
            )
            # Prefer the anomaly object when it agrees; it has the dated detail.
            line = anomaly_line(grounded) if grounded is not None else quoted_line
            return line + (" " + reduction_note() if wants_reduction else "")

        # Prefer the category the user actually named; only fall back to the
        # largest anomaly when the question does not point at one category.
        named = [
            str(a.get("category"))
            for a in anomalies
            if mentioned(str(a.get("category", "")))
        ]
        if not named:
            named = [
                str(t.get("category"))
                for t in trends
                if mentioned(str(t.get("category", "")))
            ]
        if not named:
            named = [c for c in totals if mentioned(c)]

        if named:
            category = named[0]
            hit = next(
                (a for a in anomalies if str(a.get("category")) == category),
                None,
            )
            if hit is not None:
                return anomaly_line(hit) + (" " + reduction_note() if wants_reduction else "")
            trend = next(
                (t for t in trends if str(t.get("category")) == category),
                None,
            )
            if trend is not None:
                return trend_line(trend)
            if category in totals:
                return total_line(category)
            other = anomaly_line(anomalies[0]) if anomalies else ""
            honest = (
                f"I don't have a flagged unusual {label(category)} expense to analyze yet."
                + (f" {other}" if other else "")
            )
            return honest + (" " + reduction_note() if wants_reduction else "")

        if anomalies and anomaly_asked:
            return anomaly_line(anomalies[0]) + (" " + reduction_note() if wants_reduction else "")

        if totals:
            category = max(totals, key=totals.get)
            summary = f"Your highest spending category is {category} at SGD {totals[category]:.2f}."
            if wants_reduction:
                summary += (
                    " The biggest lever is usually this category: review its largest transactions "
                    "and set a monthly limit to keep it in check."
                )
            return summary
        return "No recent transactions were provided."

    @staticmethod
    def _specialist(prompt_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        grounding = payload.get("grounding", {})
        if prompt_id.endswith("spending"):
            summary = LocalFixtureModelGateway._spending_summary(payload, grounding)
        elif prompt_id.endswith("budget"):
            if grounding.get("capacity_source") == "confirmed_plan":
                capacity = grounding["capacity"]
                summary = f"Your confirmed {capacity['period_start']} budget sets aside SGD {capacity['estimated_savings_capacity']:.2f} monthly savings, with SGD {capacity['unallocated_income']:.2f} unallocated. This is a planned allocation, not a savings balance."
            elif grounding.get("income", 0) == 0:
                summary = "Add monthly income and recurring expenses to generate a personalized budget."
            else:
                summary = (
                    "After recurring expenses, estimated disposable income is SGD "
                    f"{grounding['disposable_income']:.2f}. This is an illustrative fallback without a confirmed plan."
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
            capacity = grounding.get("monthly_savings_capacity", {})
            if capacity:
                summary += f" Capacity source: {capacity.get('source', 'illustrative_fallback')}; budget month: {capacity.get('period_start') or 'unspecified'}."
                combined = grounding.get("combined_feasibility", {})
                if combined:
                    summary += f" For all listed goals together, the monthly shortfall is SGD {combined['monthly_shortfall']:.2f}; they share one pool."
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
                translations = load_data("offline_education_zh")
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
            "rationale": [translate("education.allowlisted_grounding", grounding.get("response_language"))],
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
                        translate("education.investment_outcomes", grounding.get("response_language"))
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
        policy = self.settings.model_policy(component, max_tokens)
        if trace_id:
            with self._lock:
                calls = self._calls.get(trace_id)
                if calls is None:
                    raise ModelGatewayError(
                        "The workflow has already closed.",
                        code="WORKFLOW_CLOSED", component="model_budget",
                    )
                if self.settings.model_provider.lower() != "local_fixture" and any(
                    item.get("status") == "failed"
                    and any(type(item.get(key)) is not int for key in ("input_tokens", "output_tokens", "total_tokens"))
                    for item in calls
                ):
                    raise ModelGatewayError(
                        "No further model calls are permitted while consumed usage is unknown.",
                        code="MODEL_USAGE_UNKNOWN", component="model_budget",
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
                    "model_id": policy.model_id,
                    "reasoning_effort": policy.reasoning_effort,
                    "max_output_tokens": policy.max_tokens,
                    "temperature_supported": self.settings.model_provider.lower() == "bedrock",
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

        log_event(
            "model.generation.started", call_id=call_id, trace_id=trace_id,
            component=component, provider=self.settings.model_provider,
            model_id=policy.model_id, input_characters=len(user_prompt),
        )
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
            error_code = getattr(exc, "code", type(exc).__name__)
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
                    "reasoning_tokens": getattr(generation, "provider_metrics", {}).get("reasoningTokens"),
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
