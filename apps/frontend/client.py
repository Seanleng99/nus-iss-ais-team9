import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx


def build_snapshot(
    monthly_income: float,
    housing: float,
    food: float,
    transport: float,
) -> dict:
    expenses = []
    occurred_on = datetime.now(UTC).date().isoformat()
    for description, category, amount in (
        ("Housing", "housing", housing),
        ("Food", "food", food),
        ("Transport", "transport", transport),
    ):
        if amount > 0:
            expenses.append(
                {
                    "description": description,
                    "category": category,
                    "amount": {"currency": "SGD", "amount": amount},
                    "occurred_on": occurred_on,
                }
            )
    snapshot = {"recurring_expenses": expenses}
    if monthly_income > 0:
        snapshot["monthly_income"] = {"currency": "SGD", "amount": monthly_income}
    return snapshot


def build_request(user_id: str, message: str, snapshot: dict) -> dict:
    return {
        "user_id": user_id.strip() or "demo-user",
        "session_id": str(uuid4()),
        "message": message.strip(),
        "snapshot": snapshot,
    }


def ask_coach(payload: dict) -> dict:
    base_url = os.getenv("BACKEND_BASE_URL", "http://localhost:8080").rstrip("/")
    api_key = os.getenv("BACKEND_API_KEY", "change-me-locally")
    response = httpx.post(
        f"{base_url}/api/coach",
        headers={"X-API-Key": api_key},
        json=payload,
        timeout=45,
    )
    response.raise_for_status()
    return response.json()
