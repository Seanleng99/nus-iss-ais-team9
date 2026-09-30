import os
import re
from contextlib import nullcontext
from datetime import date
from functools import wraps
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from ui.response_metadata import response_metadata
from ui.telemetry import (
    call_span,
    context_fields,
    log_event,
    outbound_headers,
    trace_context,
    trace_method,
)


def _trace_operation(function):
    traced = trace_method(function)

    @wraps(function)
    def wrapped(self, *args, **kwargs):
        current = context_fields()
        context = (
            nullcontext()
            if current.get("correlation_id")
            else trace_context(
                journey_id=self.journey_id,
                parent_span_id=current.get("span_id"),
                caller_method=current.get("method"),
            )
        )
        with context:
            return traced(self, *args, **kwargs)

    return wrapped


def _route_template(path: str) -> str:
    if path in {"/api/profiles", "/api/coach", "/api/coach/traces"}:
        return path
    if re.fullmatch(r"/api/coach/traces/[^/?#]+", path):
        return "/api/coach/traces/{trace_id}"
    match = re.fullmatch(
        r"/api/users/[^/?#]+/(profile|data-lifecycle|memory-consent|data-export|data|"
        r"fairness-profile|fairness-consent|demographics|transactions|goals|budget|"
        r"dashboard|chat-sessions)", path,
    )
    if match:
        return f"/api/users/{{user_id}}/{match[1]}"
    match = re.fullmatch(r"/api/users/[^/?#]+/(transactions|goals|chat-sessions)/[^/?#]+", path)
    if match:
        identifier = {"transactions": "transaction_id", "goals": "goal_id", "chat-sessions": "session_id"}
        return f"/api/users/{{user_id}}/{match[1]}/{{{identifier[match[1]]}}}"
    return "<unmatched>"


class BackendClient:
    def __init__(
        self,
        base_url: str | None = None,
        id_token: str | None = None,
        automation_api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        journey_id: str | None = None,
        synthetic_log: bool = False,
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
        self.journey_id = journey_id
        self.synthetic_log = bool(
            synthetic_log and not id_token
            and (automation_api_key or os.getenv("BACKEND_API_KEY"))
        )

    def _authentication_headers(self) -> dict[str, str]:
        if self.id_token:
            return {"Authorization": f"Bearer {self.id_token}"}
        if self.automation_api_key:
            return {"X-API-Key": self.automation_api_key}
        raise RuntimeError("An authenticated user session is required")

    @_trace_operation
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
        metadata = {"http_method": method, "route": _route_template(path)}
        log_event("http.request_started", **metadata)
        headers = {**self._authentication_headers(), **outbound_headers()}
        if self.synthetic_log and not self.id_token and self.automation_api_key and path == "/api/coach":
            headers["X-Synthetic-Log"] = "true"
        with httpx.Client(
            base_url=self.base_url,
            headers=headers,
            transport=self.transport,
            timeout=timeout,
        ) as client:
            response = client.request(method, path, json=json, params=params)
        log_event(
            "http.response_received", status_code=response.status_code,
            response_bytes=len(response.content), **metadata,
        )
        if allow_not_found and response.status_code == 404:
            log_event("http.response_accepted", status_code=404, status="not_found", **metadata)
            return None
        with call_span("httpx._models.Response.raise_for_status"):
            response.raise_for_status()
        if response.status_code == 204:
            log_event("http.response_accepted", status_code=204, status="empty", **metadata)
            return None
        with call_span("httpx._models.Response.json"):
            result = response.json()
        log_event(
            "http.response_accepted", status_code=response.status_code,
            **metadata, **response_metadata(result),
        )
        return result

    @_trace_operation
    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        return self._request("GET", f"/api/users/{user_id}/profile", allow_not_found=True)

    @_trace_operation
    def list_profiles(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/profiles")

    @_trace_operation
    def create_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/profiles", json=payload)

    @_trace_operation
    def save_profile(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/profile", json=payload)

    @_trace_operation
    def delete_profile(self, user_id: str) -> bool:
        self._request("DELETE", f"/api/users/{user_id}/profile")
        return True

    @_trace_operation
    def get_data_lifecycle(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/data-lifecycle")

    @_trace_operation
    def save_memory_consent(self, user_id: str, granted: bool) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/api/users/{user_id}/memory-consent",
            json={"granted": granted},
        )

    @_trace_operation
    def export_user_data(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/data-export")

    @_trace_operation
    def delete_user_data(self, user_id: str, policy_version: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/users/{user_id}/data",
            json={
                "confirm_user_id": user_id,
                "policy_version": policy_version,
            },
        )

    @_trace_operation
    def get_fairness_profile(self, user_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/fairness-profile")

    @_trace_operation
    def save_fairness_consent(self, user_id: str, granted: bool) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/api/users/{user_id}/fairness-consent",
            json={"granted": granted},
        )

    @_trace_operation
    def save_demographics(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/demographics", json=payload)

    @_trace_operation
    def list_transactions(
        self, user_id: str, period_start: date | None = None
    ) -> list[dict[str, Any]]:
        params = {"period_start": period_start.isoformat()} if period_start else None
        return self._request(
            "GET",
            f"/api/users/{user_id}/transactions",
            params=params,
        )

    @_trace_operation
    def create_transaction(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/users/{user_id}/transactions", json=payload)

    @_trace_operation
    def update_transaction(
        self, user_id: str, transaction_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "PUT", f"/api/users/{user_id}/transactions/{transaction_id}", json=payload
        )

    @_trace_operation
    def delete_transaction(self, user_id: str, transaction_id: str) -> None:
        self._request("DELETE", f"/api/users/{user_id}/transactions/{transaction_id}")

    @_trace_operation
    def list_goals(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/users/{user_id}/goals")

    @_trace_operation
    def create_goal(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/users/{user_id}/goals", json=payload)

    @_trace_operation
    def update_goal(
        self, user_id: str, goal_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/goals/{goal_id}", json=payload)

    @_trace_operation
    def delete_goal(self, user_id: str, goal_id: str) -> None:
        self._request("DELETE", f"/api/users/{user_id}/goals/{goal_id}")

    @_trace_operation
    def get_budget(self, user_id: str, period_start: date) -> dict[str, Any] | None:
        return self._request(
            "GET",
            f"/api/users/{user_id}/budget",
            params={"period_start": period_start.isoformat()},
            allow_not_found=True,
        )

    @_trace_operation
    def preview_budget_months(self, user_id, payload):
        return self._request("POST", f"/api/users/{user_id}/budget/continuity/preview", json=payload)

    def confirm_budget_months(self, user_id, preview_id):
        return self._request("POST", f"/api/users/{user_id}/budget/continuity/confirm", json={"preview_id": preview_id, "confirmed": True})

    def get_review_preferences(self, user_id):
        return self._request("GET", f"/api/users/{user_id}/budget/reviews/preferences")

    def save_review_preferences(self, user_id, payload):
        return self._request("PUT", f"/api/users/{user_id}/budget/reviews/preferences", json=payload)

    def get_due_review(self, user_id):
        return self._request("GET", f"/api/users/{user_id}/budget/reviews/due")

    def acknowledge_budget_review(self, user_id, evidence):
        return self._request("POST", f"/api/users/{user_id}/budget/reviews/acknowledge", json={"evidence": evidence, "confirmed": True})

    def get_budget_commitments(self, user_id, period):
        return self._request("GET", f"/api/users/{user_id}/budget/commitments", params={"period_start": period.isoformat()})

    def save_budget_commitments(self, user_id, payload):
        return self._request("PUT", f"/api/users/{user_id}/budget/commitments", json=payload)

    def budget_alternatives(self, user_id, payload):
        return self._request("POST", f"/api/users/{user_id}/budget/alternatives", json=payload)

    def get_budget_timing(self, user_id, period):
        return self._request("GET", f"/api/users/{user_id}/budget/timing", params={"period_start": period.isoformat()})

    def get_budget_workspace(self, user_id):
        return self._request("GET", f"/api/users/{user_id}/budget/workspace")

    def preview_workspace_change(self, user_id, operation, payload):
        import json
        return self._request("POST", f"/api/users/{user_id}/budget/workspace/preview",
                             json={"operation": operation, "payload_json": json.dumps(payload)})

    def confirm_workspace_change(self, user_id, preview_id):
        return self._request("POST", f"/api/users/{user_id}/budget/workspace/confirm",
                             json={"preview_id": preview_id, "confirmed": True})

    def get_cashflow_settings(self, user_id):
        return self._request("GET", f"/api/users/{user_id}/cashflow/settings")

    def save_cashflow_settings(self, user_id, payload):
        return self._request("PUT", f"/api/users/{user_id}/cashflow/settings", json=payload)

    def get_cashflow(self, user_id, through):
        return self._request("GET", f"/api/users/{user_id}/cashflow", params={"through": through.isoformat()})

    def settle_cashflow(self, user_id, schedule_id, due_on, *, settled=True):
        return self._request("POST", f"/api/users/{user_id}/cashflow/settle", params={"schedule_id": schedule_id, "due_on": due_on.isoformat(), "settled": settled})

    @_trace_operation
    def review_budget(self, user_id: str, period_start: date) -> dict[str, Any]:
        return self._request("GET", f"/api/users/{user_id}/budget/review", params={"period_start": period_start.isoformat()})

    @_trace_operation
    def compare_budget(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"/api/users/{user_id}/budget/compare", json=payload)

    @_trace_operation
    def save_budget(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("PUT", f"/api/users/{user_id}/budget", json=payload)

    @_trace_operation
    def get_dashboard(self, user_id: str, period_start: date) -> dict[str, Any] | None:
        return self._request(
            "GET",
            f"/api/users/{user_id}/dashboard",
            params={"period_start": period_start.isoformat()},
            allow_not_found=True,
        )

    @_trace_operation
    def ask_coach(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/coach", json=payload, timeout=60.0)

    @_trace_operation
    def list_traces(self, user_id: str, *, status: str | None = None, offset: int = 0) -> dict:
        params = {"user_id": user_id, "offset": offset, "limit": 25}
        if status is not None:
            params["status"] = status
        return self._request("GET", "/api/coach/traces", params=params)

    @_trace_operation
    def get_trace(self, user_id: str, trace_id: str) -> dict | None:
        return self._request("GET", f"/api/coach/traces/{quote(trace_id, safe='')}",
                             params={"user_id": user_id}, allow_not_found=True)

    @_trace_operation
    def list_chat_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return self._request("GET", f"/api/users/{user_id}/chat-sessions")

    @_trace_operation
    def create_chat_session(
        self, user_id: str, title: str, session_id: str | None = None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/users/{user_id}/chat-sessions",
            json={"id": session_id or str(uuid4()), "title": title},
        )

    @_trace_operation
    def get_chat_session(self, user_id: str, session_id: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/api/users/{user_id}/chat-sessions/{session_id}"
        )

    @_trace_operation
    def rename_chat_session(
        self, user_id: str, session_id: str, title: str
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/api/users/{user_id}/chat-sessions/{session_id}",
            json={"title": title},
        )

    @_trace_operation
    def delete_chat_session(self, user_id: str, session_id: str) -> None:
        self._request("DELETE", f"/api/users/{user_id}/chat-sessions/{session_id}")


@trace_method
def build_request(
    user_id: str, message: str, session_id: str | None = None
) -> dict[str, Any]:
    return {
        "user_id": user_id.strip() or "demo-user",
        "session_id": session_id or str(uuid4()),
        "message": message.strip(),
    }


@trace_method
def ask_coach(payload: dict[str, Any]) -> dict[str, Any]:
    return BackendClient().ask_coach(payload)
