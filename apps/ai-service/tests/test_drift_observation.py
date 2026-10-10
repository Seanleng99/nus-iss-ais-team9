import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from coach_trace import safe_details

from app.core import drift


@pytest.mark.parametrize("message,language", json.loads(
    Path(__file__).with_name("fixtures").joinpath("drift_observation_cases.json").read_text(encoding="utf-8")))
def test_observations_retain_only_bounded_buckets(message, language):
    request = SimpleNamespace(message=message)
    response = SimpleNamespace(selected_agents=["budget", "spending"], blocked=False,
        audit={"model_id": "model", "prompt_content_hash": "hash"},
        agent_results=[SimpleNamespace(data={"needs_input": True})])
    observed = safe_details(drift.observation(request, response))
    assert observed["input_language"] == language
    assert observed["agent_mix"] == "budget.spending"
    assert observed["needs_input"] is True
    assert observed["input_length_band"] == "short"
    assert "PRIVATE" not in json.dumps(observed)
    assert "message" not in observed


def test_capture_intent_and_long_length_use_fixed_buckets(monkeypatch):
    events = []
    monkeypatch.setattr(drift, "log_event", lambda event, *names, **fields: events.append((event, names, fields)))
    drift.log_observation(SimpleNamespace(message="x" * 501),
        SimpleNamespace(selected_agents=[], blocked=True, agent_results=[], audit={"goal_capture": True}))
    assert events[0] == ("VV entering ", ("app.core.drift", "log_observation"), {})
    observations = [fields for event, _, fields in events if event == "coach.drift.observation"]
    assert len(observations) == 1
    assert observations[0]["intent_bucket"] == "capture_goal"
    assert observations[0]["input_length_band"] == "long"
    assert observations[0]["agent_mix"] == "none"
