import httpx

from app.core.config import Settings
from app.core.observability import get_correlation_id
from app.domain.schemas import CoachRequest, CoachResponse


class AIServiceUnavailableError(RuntimeError):
    """Raised when the private AI service cannot produce a valid response."""


class AIServiceClient:
    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.ai_service_base_url.rstrip("/")
        self._api_key = settings.ai_service_api_key
        self._timeout = settings.ai_service_timeout_seconds

    async def coach(self, request: CoachRequest) -> CoachResponse:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                headers = {"X-API-Key": self._api_key}
                if correlation_id := get_correlation_id():
                    headers["X-Correlation-ID"] = correlation_id
                response = await client.post(
                    f"{self._base_url}/coach",
                    headers=headers,
                    json=request.model_dump(mode="json"),
                )
                response.raise_for_status()
                return CoachResponse.model_validate(response.json())
        except (httpx.HTTPError, ValueError) as error:
            raise AIServiceUnavailableError from error
