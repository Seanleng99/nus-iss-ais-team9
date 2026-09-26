import logging

import httpx

from app.core.config import Settings
from app.core.telemetry import call_span, log_event, outbound_headers, trace_method
from app.domain.schemas import CoachRequest, CoachResponse


class AIServiceUnavailableError(RuntimeError):
    """Raised when the private AI service cannot produce a valid response."""


class AIServiceClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_service_base_url.rstrip("/")
        self._api_key = settings.ai_service_api_key
        self._timeout = settings.ai_service_timeout_seconds

    @trace_method
    async def coach(self, request: CoachRequest) -> CoachResponse:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                headers = {"X-API-Key": self._api_key, **outbound_headers()}
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
        except (httpx.HTTPError, ValueError) as error:
            log_event(
                "ai_service.failed",
                level=logging.ERROR,
                exception_type=type(error).__name__,
                status_code=(
                    error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                ),
            )
            raise AIServiceUnavailableError from error
