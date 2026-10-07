import asyncio
import json
import logging

import httpx

from app.core.config import Settings
from app.core.run_trace import active_run, record_event
from app.core.telemetry import call_span, log_event, outbound_headers, trace_method
from app.domain.schemas import CoachRequest, CoachResponse


class AIServiceUnavailableError(RuntimeError):
    """Raised when the private AI service cannot produce a valid response."""

    def __init__(self, *, timed_out=False, timeout_origin=None):
        super().__init__("AI service unavailable")
        self.timed_out = timed_out
        self.timeout_origin = timeout_origin


class AIServiceClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_service_base_url.rstrip("/")
        self._api_key = settings.ai_service_api_key
        self._timeout = settings.ai_service_timeout_seconds
        self._composition_timeout = min(self._timeout, settings.ai_service_composition_timeout_seconds)

    @trace_method
    async def compose(self, request: CoachRequest, response: CoachResponse, outcomes: list[dict]) -> CoachResponse:
        # During action composition DurableRun buffers stream events. Financial
        # writes and final trace completion therefore share one atomic commit.
        try:
            async with asyncio.timeout(self._composition_timeout):
                async with httpx.AsyncClient(timeout=self._composition_timeout) as client:
                    run = active_run.get()
                    if run is not None:
                        return await self._stream(client, request,
                            {"X-API-Key": self._api_key, "X-Workflow-ID": run.trace_id, **outbound_headers()}, run,
                            path="/coach/compose/stream",
                            payload={"request": request.model_dump(mode="json"),
                                     "response": response.model_dump(mode="json"), "outcomes": outcomes})
                    result = await client.post(
                        f"{self._base_url}/coach/compose",
                        headers={"X-API-Key": self._api_key, **outbound_headers()},
                        json={"request": request.model_dump(mode="json"),
                              "response": response.model_dump(mode="json"), "outcomes": outcomes},
                    )
                    result.raise_for_status()
                    return CoachResponse.model_validate(result.json())
        except (httpx.HTTPError, ValueError, TimeoutError, TypeError, KeyError) as error:
            log_event("ai_service.composition.failed", exception_type=type(error).__name__)
            raise AIServiceUnavailableError(
                timed_out=isinstance(error, (httpx.TimeoutException, TimeoutError)),
            ) from error

    @trace_method
    async def coach(self, request: CoachRequest) -> CoachResponse:
        record_event("backend.ai.deadline", timeout_seconds=self._timeout, component="ai_transport")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                headers = {"X-API-Key": self._api_key, **outbound_headers()}
                headers["X-Workflow-Timeout-Seconds"] = str(max(1, min(115, self._timeout - 5)))
                run = active_run.get()
                if run is not None:
                    headers["X-Workflow-ID"] = run.trace_id
                    async with asyncio.timeout(self._timeout):
                        return await self._stream(client, request, headers, run)
                response = await client.post(
                    f"{self._base_url}/coach",
                    headers=headers,
                    json=request.model_dump(mode="json"),
                )
                log_event("ai_service.response", status_code=response.status_code)
                response.raise_for_status()
                with call_span(
                    "pydantic.main.BaseModel.model_validate", response_type="CoachResponse"
                ):
                    result = CoachResponse.model_validate(response.json())
                log_event("ai_service.response.validated", response_type="CoachResponse")
                return result
        except (
            httpx.HTTPError,
            ValueError,
            TimeoutError,
            KeyError,
            TypeError,
            AttributeError,
        ) as error:
            log_event(
                "ai_service.failed",
                level=logging.ERROR,
                exception_type=type(error).__name__,
                status_code=(
                    error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                ),
            )
            raise AIServiceUnavailableError(
                timed_out=isinstance(error, (httpx.TimeoutException, TimeoutError)),
                timeout_origin=("workflow" if isinstance(error, TimeoutError) else
                                "transport" if isinstance(error, httpx.TimeoutException) else None),
            ) from error

    async def _stream(self, client, request, headers, run, *, path="/coach/stream", payload=None):
        async with client.stream(
            "POST",
            f"{self._base_url}{path}",
            headers=headers,
            json=payload if payload is not None else request.model_dump(mode="json"),
        ) as response:
            log_event("ai_service.response", status_code=response.status_code)
            response.raise_for_status()
            if "application/x-ndjson" not in response.headers.get("content-type", ""):
                raise ValueError("AI service does not support durable trace streaming")
            async for line in response.aiter_lines():
                if not line:
                    continue
                if len(line) > 2_000_000:
                    raise ValueError("Trace frame exceeds size limit")
                item = json.loads(line)
                if item.get("type") == "event":
                    run.append(item["event"])
                elif item.get("type") == "response":
                    with call_span(
                        "pydantic.main.BaseModel.model_validate", response_type="CoachResponse"
                    ):
                        result = CoachResponse.model_validate(item["response"])
                    if result.audit.get("trace_id") != run.trace_id:
                        raise ValueError("Mismatched workflow ID")
                    log_event("ai_service.response.validated", response_type="CoachResponse")
                    return result
                elif item.get("type") == "error":
                    log_event(
                        "ai_service.failed", error_code="AI_WORKFLOW_FAILED", trace_id=run.trace_id
                    )
                    code = item.get("code")
                    timed_out = code in {"AGENT_TIMEOUT", "WORKFLOW_TIMEOUT", "OPENAI_TIMEOUT"}
                    raise AIServiceUnavailableError(timed_out=timed_out,
                        timeout_origin={"AGENT_TIMEOUT": "specialist", "WORKFLOW_TIMEOUT": "workflow",
                                        "OPENAI_TIMEOUT": "model"}.get(code))
                else:
                    raise ValueError("Invalid trace frame")
            raise ValueError("Incomplete trace stream")
