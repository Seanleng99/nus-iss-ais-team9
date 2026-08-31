import os
from datetime import date
from typing import Any
from uuid import uuid4

import httpx


class BackendClient:
    def __init__(
        self,
        base_url: str | None = None,
        id_token: str | None = None,
        automation_api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("BACKEND_BASE_URL", "http://localhost:8080")
        ).rstrip("/")
        self.id_token = id_token
        self.automation_api_key = automation_api_key
        if not self.id_token and not self.automation_api_key:
            configured_automation_key = os.getenv("BACKEND_API_KEY")
            if configured_automation_key:
                self.automation_api_key = configured_automation_key
            elif os.getenv("APP_ENV", "local").casefold() == "local":
                self.automation_api_key = "change-me-locally"
        self.transport = transport

    def _authentication_headers(self) -> dict[str, str]:
        if self.id_token:
            return {"Authorization": f"Bearer {self.id_token}"}
        if self.automation_api_key:
            return {"X-API-Key": self.automation_api_key}
        raise RuntimeError("An authenticated user session is required")

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
            headers=self._authentication_headers(),
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

    def list_profiles(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/profiles")

    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/profiles", json=payload)

    def save_profile(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/profile", json=payload)

    def delete_profile(self, user_id: str) -> bool:
        self._request("DELETE", f"/api/users/{user_id}/profile")
        return True

    def get_data_lifecycle(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/data-lifecycle")

    def save_memory_consent(self, user_id: str, granted: bool) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/api/users/{user_id}/memory-consent",
            json={"granted": granted},
        )

    def export_user_data(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/data-export")

    def delete_user_data(self, user_id: str, policy_version: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/users/{user_id}/data",
            json={
                "confirm_user_id": user_id,
                "policy_version": policy_version,
            },
        )

    def get_fairness_profile(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/fairness-profile")

    def save_fairness_consent(self, user_id: str, granted: bool) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/api/users/{user_id}/fairness-consent",
            json={"granted": granted},
        )

    def save_demographics(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/demographics", json=payload)

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

    def list_chat_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/users/{user_id}/chat-sessions")

    def create_chat_session(
        self, user_id: str, title: str, session_id: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/users/{user_id}/chat-sessions",
            json={"id": session_id or str(uuid4()), "title": title},
        )

    def get_chat_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/users/{user_id}/chat-sessions/{session_id}"
        )

    def rename_chat_session(
        self, user_id: str, session_id: str, title: str
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/users/{user_id}/chat-sessions/{session_id}",
            json={"title": title},
        )

    def delete_chat_session(self, user_id: str, session_id: str) -> None:
        self._request("DELETE", f"/api/users/{user_id}/chat-sessions/{session_id}")


def build_request(
    user_id: str, message: str, session_id: str | None = None
) -> dict[str, Any]:
    return {
        "user_id": user_id.strip() or "demo-user",
        "session_id": session_id or str(uuid4()),
        "message": message.strip(),
    }


def ask_coach(payload: dict[str, Any]) -> dict[str, Any]:
    return BackendClient().ask_coach(payload)
