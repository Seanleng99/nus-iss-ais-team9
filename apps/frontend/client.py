import os
from datetime import date
from typing import Any
from uuid import uuid4

import httpx


class BackendClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("BACKEND_BASE_URL", "http://localhost:8080")
        ).rstrip("/")
        self.api_key = api_key or os.getenv("BACKEND_API_KEY", "change-me-locally")
        self.transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | list[dict[str, Any]] | None = None,
        params: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        timeout: float = 20.0,
    ) -> Any:
        with httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            transport=self.transport,
            timeout=timeout,
        ) as client:
            response = client.request(method, path, json=json, params=params)
        if allow_not_found and response.status_code == 404:
            return None
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        return self._request("GET", f"/api/users/{user_id}/profile", allow_not_found=True)

    def save_profile(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/profile", json=payload)

    def list_transactions(self, user_id: str, period_start: date) -> list[dict[str, Any]]:
        return self._request(
            "GET",
            f"/api/users/{user_id}/transactions",
            params={"period_start": period_start.isoformat()},
        )

    def create_transaction(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/users/{user_id}/transactions", json=payload)

    def update_transaction(
        self, user_id: str, transaction_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PUT", f"/api/users/{user_id}/transactions/{transaction_id}", json=payload
        )

    def delete_transaction(self, user_id: str, transaction_id: str) -> None:
        self._request("DELETE", f"/api/users/{user_id}/transactions/{transaction_id}")

    def list_goals(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/users/{user_id}/goals")

    def create_goal(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/users/{user_id}/goals", json=payload)

    def update_goal(
        self, user_id: str, goal_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/goals/{goal_id}", json=payload)

    def delete_goal(self, user_id: str, goal_id: str) -> None:
        self._request("DELETE", f"/api/users/{user_id}/goals/{goal_id}")

    def get_budget(self, user_id: str, period_start: date) -> dict[str, Any] | None:
        return self._request(
            "GET",
            f"/api/users/{user_id}/budget",
            params={"period_start": period_start.isoformat()},
            allow_not_found=True,
        )

    def save_budget(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/budget", json=payload)

    def get_dashboard(self, user_id: str, period_start: date) -> dict[str, Any] | None:
        return self._request(
            "GET",
            f"/api/users/{user_id}/dashboard",
            params={"period_start": period_start.isoformat()},
            allow_not_found=True,
        )

    def ask_coach(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/coach", json=payload, timeout=60.0)


def build_request(user_id: str, message: str) -> dict[str, Any]:
    return {
        "user_id": user_id.strip() or "demo-user",
        "session_id": str(uuid4()),
        "message": message.strip(),
    }


def ask_coach(payload: dict[str, Any]) -> dict[str, Any]:
    return BackendClient().ask_coach(payload)
