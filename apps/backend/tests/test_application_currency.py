"""API currency defaults, persistence, rejection and historical record isolation."""

from copy import deepcopy
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.infrastructure.models import FinancialGoalRecord, FinancialProfileRecord, TransactionRecord
from app.main import app

BASE = "/api/users/currency-user"
PERIOD = "2026-09-01"
HEADERS = {"X-API-Key": settings.api_key}


def input_for(resource, currency):
    money = {"amount": 100, **currency}
    return {
        "profile": {"monthly_income": money},
        "transactions": {
            "description": "Food",
            "category": "food",
            "amount": money,
            "occurred_on": PERIOD,
        },
        "goals": {
            "name": "Reserve",
            "target_amount": money,
            "current_amount": {"amount": 10, **currency},
            "target_months": 12,
        },
        "budget": {
            "period_start": PERIOD,
            "categories": [{"category": "food", "limit_amount": 100}],
            **currency,
        },
        "cashflow/settings": {
            "opening_on": PERIOD,
            "opening_balance": 100,
            "confirmed": True,
            "schedules": [],
            **currency,
        },
    }[resource]


def write(client, resource, payload, record_id=None):
    method = (
        "put" if resource in {"profile", "budget", "cashflow/settings"} or record_id else "post"
    )
    path = BASE + "/" + resource + ("/" + record_id if record_id else "")
    return getattr(client, method)(path, headers=HEADERS, json=payload)


def read(client, resource):
    suffix = "?period_start=" + PERIOD if resource == "budget" else ""
    return client.get(BASE + "/" + resource + suffix, headers=HEADERS)


def currencies(resource, data):
    if resource == "profile":
        return [data["monthly_income"]["currency"]]
    if resource == "transactions":
        return [data["amount"]["currency"]]
    if resource == "goals":
        return [data[field]["currency"] for field in ("target_amount", "current_amount")]
    return [data["currency"]]


@pytest.mark.parametrize(
    "resource", ["profile", "transactions", "goals", "budget", "cashflow/settings"]
)
@pytest.mark.parametrize("currency", [{}, {"currency": None}, {"currency": "SGD"}])
def test_create_and_update_default_to_fixed_sgd(resource, currency):
    client = TestClient(app)
    client.put(BASE + "/profile", headers=HEADERS, json={})
    payload = input_for(resource, currency)
    created = write(client, resource, payload)
    assert created.status_code in {200, 201}, created.text
    assert set(currencies(resource, created.json())) == {"SGD"}
    updated = write(client, resource, payload, created.json().get("id"))
    assert updated.status_code == 200, updated.text
    stored = read(client, resource).json()
    if isinstance(stored, list):
        stored = stored[0]
    assert set(currencies(resource, stored)) == {"SGD"}


@pytest.mark.parametrize(
    "resource", ["profile", "transactions", "goals", "budget", "cashflow/settings"]
)
@pytest.mark.parametrize("currency", ["USD", "EUR"])
def test_foreign_currency_never_creates_or_updates_records(resource, currency):
    client = TestClient(app)
    client.put(BASE + "/profile", headers=HEADERS, json={})
    before = read(client, resource)
    rejected = write(client, resource, input_for(resource, {"currency": currency}))
    assert rejected.status_code == 422
    assert "SGD" in rejected.text
    assert read(client, resource).json() == before.json()
    created = write(client, resource, input_for(resource, {})).json()
    before = deepcopy(read(client, resource).json())
    rejected = write(
        client, resource, input_for(resource, {"currency": currency}), created.get("id")
    )
    assert rejected.status_code == 422
    assert read(client, resource).json() == before


def test_dashboard_excludes_foreign_history_and_record_views_preserve_labels(db_session_factory):
    client = TestClient(app)
    client.put(BASE + "/profile", headers=HEADERS, json={"monthly_income": {"amount": 1000}})
    client.post(BASE + "/transactions", headers=HEADERS, json=input_for("transactions", {}))
    with db_session_factory() as session:
        session.add(
            TransactionRecord(
                user_id="currency-user",
                description="Foreign receipt",
                category="food",
                amount=900,
                currency="USD",
                occurred_on=date(2026, 9, 1),
            )
        )
        session.add(
            FinancialGoalRecord(
                user_id="currency-user",
                name="Foreign goal",
                target_amount=1000,
                current_amount=100,
                currency="USD",
                target_months=12,
            )
        )
        session.commit()
    dashboard = client.get(BASE + "/dashboard?period_start=" + PERIOD, headers=HEADERS).json()
    assert dashboard["currency"] == "SGD"
    assert dashboard["total_spent"] == 100
    assert dashboard["available_balance"] == 900
    assert dashboard["transaction_count"] == 1
    assert dashboard["goals"] == []
    assert {row["amount"]["currency"] for row in read(client, "transactions").json()} == {
        "SGD",
        "USD",
    }
    assert read(client, "goals").json()[0]["target_amount"]["currency"] == "USD"
    budget = client.put(BASE + "/budget", headers=HEADERS, json=input_for("budget", {})).json()
    assert budget["total_spent"] == 100
    with db_session_factory() as session:
        profile = session.get(FinancialProfileRecord, "currency-user")
        profile.currency = "USD"
        session.commit()
    dashboard = client.get(BASE + "/dashboard?period_start=" + PERIOD, headers=HEADERS).json()
    assert dashboard["currency"] == "SGD"
    assert dashboard["monthly_income"] == 0
    assert read(client, "profile").json()["monthly_income"]["currency"] == "USD"
