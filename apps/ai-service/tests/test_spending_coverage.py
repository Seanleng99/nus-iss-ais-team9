"""Grounding keeps selected-month evidence and sparse historical dates distinct."""

import json

from app.agents.spending import SpendingAgent
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentTask
from app.models.gateway import LocalFixtureModelGateway


def transaction(amount, day, currency="SGD"):
    return {"description": "Dining", "category": "dining",
            "amount": {"currency": currency, "amount": amount}, "occurred_on": day}


def ground(snapshot):
    agent = SpendingAgent(LocalFixtureModelGateway(), PromptCatalog(), 0.2, 800)
    task = AgentTask(agent="spending", sanitized_message="Explain my recorded spending.", input_data=snapshot)
    return agent, task, agent._ground(task, task.sanitized_message)


def test_six_sparse_dated_records_reach_writer_with_history_and_selected_month_totals():
    records = [transaction(10, f"2026-{month:02d}-01") for month in range(1, 7)]
    agent, task, evidence = ground({
        "period_start": "2026-06-01", "recent_transactions": records[-1:],
        "historical_transactions": records[:-1],
        "transaction_context": {"period_start": "2026-06-01", "history_end": "2026-05-31",
                                "records_complete": False},
    })
    assert evidence["analysis_coverage"] == {
        "record_count": 6, "dated_record_count": 6, "distinct_recorded_days": 6,
        "first_recorded_on": "2026-01-01", "last_recorded_on": "2026-06-01", "total_amount": 60,
        "weekday": {"record_count": 4, "total_amount": 40},
        "weekend": {"record_count": 2, "total_amount": 20},
    }
    assert evidence["selected_month_coverage"]["total_amount"] == 10
    assert evidence["selected_month_coverage"]["record_count"] == 1
    assert evidence["selected_month_coverage"]["first_recorded_on"] == "2026-06-01"
    assert evidence["category_totals"] == {"dining": 10}
    assert evidence["months_analyzed"] == 6 and evidence["data_quality"] == "limited"
    assert evidence["temporal_patterns"] == []
    payload = json.loads(agent._model_message(task, task.sanitized_message, evidence))
    assert payload["analysis_results"]["analysis_coverage"]["dated_record_count"] == 6
    assert "not that dates are missing" in payload["instruction"]
    assert "do not establish a recurring habit" in payload["instruction"]


def test_selected_month_is_combined_with_prior_history_without_losing_identical_expenses():
    september = [transaction(150, "2026-09-14"), transaction(150, "2026-09-14")]
    august = [transaction(100, "2026-08-01"), transaction(50, "2026-08-31")]
    _agent, _task, evidence = ground({
        "period_start": "2026-09-01", "recent_transactions": september,
        "historical_transactions": [*august, *september, transaction(99999, "2026-10-01"),
                                    transaction(500, "2026-08-01", "USD")],
    })
    assert evidence["category_trends"][0]["current_amount"] == 300
    assert evidence["category_trends"][0]["previous_amount"] == 150
    assert evidence["analysis_coverage"]["total_amount"] == 450
    assert evidence["analysis_coverage"]["record_count"] == 4
    assert evidence["selected_month_coverage"]["record_count"] == 2
    assert evidence["selected_month_coverage"]["total_amount"] == 300
    assert evidence["excluded_currencies"] == ["USD"]


def test_legacy_history_only_snapshot_keeps_current_month_and_excludes_future_records():
    _agent, _task, evidence = ground({
        "period_start": "2026-09-01", "historical_transactions": [
            transaction(150, "2026-08-01"), transaction(300, "2026-09-14"),
            transaction(99999, "2026-10-01"),
        ],
    })
    assert evidence["category_trends"][0]["current_amount"] == 300
    assert evidence["category_trends"][0]["previous_amount"] == 150
    assert evidence["analysis_coverage"]["record_count"] == 2
    assert evidence["analysis_coverage"]["total_amount"] == 450
    assert evidence["analysis_coverage"]["last_recorded_on"] == "2026-09-14"
    assert evidence["selected_month_coverage"]["total_amount"] == 300
