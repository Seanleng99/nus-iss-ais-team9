"""Offline contract tests for the one-time Investment live acceptance harness."""

import copy
import json
from pathlib import Path

import pytest
import yaml

from infra.scripts import investment_live_acceptance as live

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = json.loads(live.MANIFEST.read_text(encoding="utf-8"))
BUILD = "a" * 40


def _ecs_fixture(*, changes=None):
    services = {}
    definitions = {}
    tasks = {}
    for role in ("ai", "backend", "frontend"):
        name = f"demo-{role}"
        task_definition = f"arn:aws:ecs:region:account:task-definition/{role}:1"
        container = {"name": role, "image": f"example/{role}:{BUILD}", "environment": []}
        if role == "ai":
            container["environment"] = [
                {"name": "MODEL_PROVIDER", "value": "openai"},
                {"name": "MODEL_ID", "value": live.MODEL},
                {"name": "RAG_PROVIDER", "value": "bedrock"},
                {"name": "POLICY_RAG_PROVIDER", "value": "bedrock"},
                {"name": "EDUCATION_KNOWLEDGE_BASE_ID", "value": "KB12345678"},
                {"name": "EDUCATION_CORPUS_VERSION", "value": MANIFEST["corpus_version"]},
                {"name": "BUILD_COMMIT", "value": BUILD},
                {"name": "OPENAI_API_KEY", "value": "do-not-retain-openai-secret"},
            ]
        elif role == "backend":
            container["environment"] = [
                {"name": "POSTGRES_HOST", "value": "postgres.internal"},
                {"name": "POSTGRES_DB", "value": "coach"},
                {"name": "POSTGRES_PASSWORD", "value": "do-not-retain-db-secret"},
            ]
        definitions[task_definition] = {"taskDefinition": {"containerDefinitions": [container]}}
        services[name] = {
            "serviceName": name,
            "status": "ACTIVE",
            "desiredCount": 1,
            "runningCount": 1,
            "pendingCount": 0,
            "deployments": [{"rolloutState": "COMPLETED"}],
            "taskDefinition": task_definition,
        }
        tasks[name] = [{
            "lastStatus": "RUNNING",
            "taskDefinitionArn": task_definition,
            "healthStatus": "HEALTHY",
            "containers": [{"image": container["image"], "imageDigest": "sha256:" + "b" * 64,
                             "lastStatus": "RUNNING"}],
        }]

    for kind, target, values in changes or []:
        if kind == "service":
            target_service = services[f"demo-{target}"]
            target_service.update(values)
        elif kind == "environment":
            env = definitions[f"arn:aws:ecs:region:account:task-definition/{target}:1"]["taskDefinition"]["containerDefinitions"][0]["environment"]
            for key, value in values.items():
                env[:] = [item for item in env if item["name"] != key]
                if value is not None:
                    env.append({"name": key, "value": value})
        elif kind == "task":
            tasks[f"demo-{target}"][0]["containers"][0].update(values)

    class FakeECS:
        def describe_services(self, *, cluster, services):
            return {"services": [services_by_name[name] for name in services if name in services_by_name],
                    "failures": []}

        def describe_task_definition(self, *, taskDefinition):
            return definitions[taskDefinition]

        def list_tasks(self, *, cluster, serviceName, desiredStatus):
            return {"taskArns": [f"task-{serviceName}"]}

        def describe_tasks(self, *, cluster, tasks):
            name = tasks[0].removeprefix("task-")
            return {"tasks": tasks_by_name[name]}

    services_by_name = services
    tasks_by_name = tasks
    return FakeECS(), {role: f"demo-{role}" for role in ("ai", "backend", "frontend")}


def _metadata(source_id):
    source = next(item for item in MANIFEST["sources"] if item["source_id"] == source_id)
    result = {key: (MANIFEST["corpus_version"] if key == "corpus_version" else source.get(key))
              for key in live.SOURCE_FIELDS}
    result["review_status"] = "approved"
    return result


class FakeBedrock:
    def __init__(self, response_factory=None):
        self.calls = []
        self.response_factory = response_factory or self._default_response

    @staticmethod
    def _default_response(call):
        query = call["retrievalQuery"]["text"]
        if "ETF" in query or "fund" in query:
            source_id = "moneysense-guide-to-etfs"
        elif "compound" in query:
            source_id = "moneysense-compound-interest"
        else:
            source_id = "moneysense-managing-investment-risk"
        return {"retrievalResults": [{"metadata": _metadata(source_id),
                                      "content": {"text": "Approved source passage."}, "score": 0.9}]}

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        return self.response_factory(kwargs)


def _source(source_id="moneysense-guide-to-etfs"):
    return _metadata(source_id)


def _answer_response(*, expected=None, evidence_status="grounded", calls=None,
                     build=BUILD, answer=None, sources=None, explanation=None):
    expected = expected or {
        "blocked": False, "selected_agents": ["investment_education"], "rag": True,
        "model_required": True, "answer_terms": ["ETF", "fund"],
    }
    sources = sources if sources is not None else [_source()]
    if answer is None:
        answer = "An ETF is a fund that trades on an exchange."
        if sources:
            answer += f" [MoneySense]({sources[0]['canonical_url']})"
    calls = calls if calls is not None else [{
        "model_id": live.MODEL, "status": "completed", "input_tokens": 12,
        "output_tokens": 8, "duration_ms": 25,
    }]
    input_tokens = sum(call.get("input_tokens", 0) for call in calls)
    output_tokens = sum(call.get("output_tokens", 0) for call in calls)
    agent_data = {"evidence_status": evidence_status}
    if evidence_status == "hybrid":
        agent_data["general_knowledge"] = ["A clearly labelled general explanation."]
    return {
        "answer": answer,
        "blocked": expected["blocked"],
        "selected_agents": expected["selected_agents"],
        "sources": sources,
        "agent_results": [{"agent": "investment_education", "data": agent_data,
                           "summary": explanation if explanation is not None else "An ETF is a fund."}],
        "audit": {
            "build_commit": build, "model_provider": "openai", "model_id": live.MODEL,
            "model_calls": calls, "model_call_count": len(calls),
            "model_input_tokens": input_tokens, "model_output_tokens": output_tokens,
            "composition_usage_complete": True, "answer_status": "answered",
        },
    }


def _checks(response, expected, previous=None):
    return {item["check"]: item["passed"] for item in live.evaluate_turn(
        response, expected, MANIFEST, BUILD, previous=previous,
    )}


@pytest.mark.parametrize("changes", [
    [("service", "ai", {"pendingCount": 1})],
    [("service", "backend", {"deployments": [{"rolloutState": "IN_PROGRESS"}]})],
])
def test_capture_aws_rejects_unstable_services(changes):
    ecs, services = _ecs_fixture(changes=changes)
    with pytest.raises(ValueError, match="^ECS_NOT_STABLE_"):
        live.capture_aws(ecs, "demo", services)


def test_capture_aws_rejects_missing_service():
    ecs, services = _ecs_fixture()
    ecs.describe_services = lambda **kwargs: {"services": [], "failures": [{"reason": "MISSING"}]}
    with pytest.raises(ValueError, match="ECS_SERVICES_MISSING"):
        live.capture_aws(ecs, "demo", services)


@pytest.mark.parametrize("changes", [
    [("environment", "ai", {"MODEL_PROVIDER": "bedrock"})],
    [("environment", "ai", {"MODEL_ID": "other-model"})],
    [("environment", "ai", {"RAG_PROVIDER": None})],
    [("environment", "ai", {"BUILD_COMMIT": "not-a-commit"})],
])
def test_capture_aws_rejects_unverified_live_provider_or_build(changes):
    ecs, services = _ecs_fixture(changes=changes)
    with pytest.raises(ValueError, match="LIVE_PROVIDERS_OR_BUILD_NOT_VERIFIED"):
        live.capture_aws(ecs, "demo", services)


def test_capture_aws_rejects_unverified_container_image():
    ecs, services = _ecs_fixture(changes=[("task", "ai", {"imageDigest": None})])
    with pytest.raises(ValueError, match="RUNNING_TASKS_NOT_VERIFIED_AI"):
        live.capture_aws(ecs, "demo", services)


def test_capture_aws_requires_postgres_history():
    ecs, services = _ecs_fixture(changes=[("environment", "backend", {"POSTGRES_HOST": None})])
    with pytest.raises(ValueError, match="POSTGRES_NOT_CONFIGURED"):
        live.capture_aws(ecs, "demo", services)


def test_capture_aws_returns_only_allowlisted_nonsecret_deployment_facts():
    ecs, services = _ecs_fixture()
    result = live.capture_aws(ecs, "demo", services)
    serialized = json.dumps(result)
    assert result["ai"]["config"]["MODEL_PROVIDER"] == "openai"
    assert result["ai"]["config"]["BUILD_COMMIT"] == BUILD
    assert result["backend"]["config"]["postgres_configured"] is True
    assert result["ai"]["image_digests"] == ["sha256:" + "b" * 64]
    assert "do-not-retain" not in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "POSTGRES_PASSWORD" not in serialized


def test_bedrock_probe_uses_five_results_and_approved_current_corpus_filter():
    client = FakeBedrock()
    case = {"id": "etf", "query": "Explain ETFs", "expected_source_ids": ["moneysense-guide-to-etfs"]}
    records = live.bedrock_probe(client, "KB12345678", [case], MANIFEST)
    call = client.calls[0]
    assert call["knowledgeBaseId"] == "KB12345678"
    assert call["retrievalQuery"] == {"text": case["query"]}
    vector = call["retrievalConfiguration"]["vectorSearchConfiguration"]
    assert vector["numberOfResults"] == 5
    assert vector["filter"] == {"andAll": [
        {"equals": {"key": "corpus_version", "value": MANIFEST["corpus_version"]}},
        {"equals": {"key": "review_status", "value": "approved"}},
    ]}
    assert records[0]["passed"] is True
    assert records[0]["expected_source_hit_at_5"] is True
    assert records[0]["results"][0]["text"] == "Approved source passage."
    assert records[0]["results"][0]["source"] == {
        key: _metadata("moneysense-guide-to-etfs")[key] for key in live.SOURCE_FIELDS
    }


@pytest.mark.parametrize("fault", [
    "wrong_corpus", "wrong_checksum", "wrong_url", "wrong_title", "wrong_version",
    "wrong_organization", "unknown_source", "unapproved", "empty_text", "query_miss",
])
def test_bedrock_probe_rejects_manifest_mismatch_empty_text_or_expected_source_miss(fault):
    case = {"id": "etf", "query": "Explain ETFs", "expected_source_ids": ["moneysense-guide-to-etfs"]}

    def response(_call):
        metadata = _metadata("moneysense-guide-to-etfs")
        text = "Approved source passage."
        if fault == "wrong_corpus":
            metadata["corpus_version"] = "stale-corpus"
        elif fault == "wrong_checksum":
            metadata["checksum"] = "sha256:" + "0" * 64
        elif fault == "wrong_url":
            metadata["canonical_url"] = "https://wrong.example/source"
        elif fault == "wrong_title":
            metadata["title"] = "Unmanifested title"
        elif fault == "wrong_version":
            metadata["document_version"] = "unmanifested-version"
        elif fault == "wrong_organization":
            metadata["issuing_organization"] = "Unapproved organization"
        elif fault == "unknown_source":
            metadata["source_id"] = "unapproved-source"
        elif fault == "unapproved":
            metadata["review_status"] = "pending"
        elif fault == "empty_text":
            text = "  "
        elif fault == "query_miss":
            metadata = _metadata("moneysense-compound-interest")
        return {"retrievalResults": [{"metadata": metadata, "content": {"text": text}}]}

    records = live.bedrock_probe(FakeBedrock(response), "KB12345678", [case], MANIFEST)
    assert records[0]["passed"] is False
    assert records[0]["expected_source_hit_at_5"] is False


@pytest.mark.parametrize("fault", ["manifest_status", "source_review", "content_review", "withdrawn"])
def test_bedrock_probe_rejects_sources_in_ineligible_manifest(fault):
    manifest = copy.deepcopy(MANIFEST)
    source = next(item for item in manifest["sources"] if item["source_id"] == "moneysense-guide-to-etfs")
    if fault == "manifest_status":
        manifest["manifest_status"] = "draft"
    elif fault == "source_review":
        source["source_review_status"] = "pending"
    elif fault == "content_review":
        source["content_review_status"] = "pending"
    else:
        source["withdrawn_at"] = "2026-10-01"
    case = {"id": "etf", "query": "Explain ETFs", "expected_source_ids": ["moneysense-guide-to-etfs"]}
    records = live.bedrock_probe(FakeBedrock(), "KB12345678", [case], manifest)
    assert records[0]["passed"] is False
    assert records[0]["expected_source_hit_at_5"] is False


@pytest.mark.parametrize("evidence_status", ["grounded", "hybrid"])
def test_evaluate_turn_accepts_real_openai_build_and_cited_grounded_or_hybrid_answer(evidence_status):
    expected = {"blocked": False, "selected_agents": ["investment_education"], "rag": True,
                "model_required": True, "answer_terms": ["ETF", "fund"]}
    checks = _checks(_answer_response(expected=expected, evidence_status=evidence_status), expected)
    assert all(checks.values()), checks
    assert checks["real_model_called"] is True
    assert checks["deployed_build_matches"] is True
    assert checks["manifest_matched_citations"] is True
    assert checks["clickable_citations"] is True


def test_evaluate_turn_rejects_missing_citations():
    expected = {"blocked": False, "selected_agents": ["investment_education"], "rag": True,
                "model_required": True, "answer_terms": ["ETF", "fund"]}
    response = _answer_response(expected=expected, sources=[])
    checks = _checks(response, expected)
    assert checks["manifest_matched_citations"] is False
    assert checks["clickable_citations"] is False


@pytest.mark.parametrize("change", ["provider", "model", "no_call", "build"])
def test_evaluate_turn_requires_openai_model_execution_and_deployed_build(change):
    expected = {"blocked": False, "selected_agents": ["investment_education"], "rag": False,
                "model_required": True, "answer_terms": ["ETF", "fund"]}
    response = _answer_response(expected=expected)
    if change == "provider":
        response["audit"]["model_provider"] = "bedrock"
    elif change == "model":
        response["audit"]["model_id"] = "wrong-model"
    elif change == "no_call":
        response["audit"].update(model_calls=[], model_call_count=0,
                                  model_input_tokens=0, model_output_tokens=0)
    else:
        response["audit"]["build_commit"] = "c" * 40
    checks = _checks(response, expected)
    assert checks["model_provider"] is (change not in {"provider", "model"})
    assert checks["deployed_build_matches"] is (change != "build")
    if change == "no_call":
        assert checks["real_model_called"] is False


@pytest.mark.parametrize("field,value", [
    ("model_id", "unexpected-model"),
    ("status", "failed"),
    ("input_tokens", -1),
    ("output_tokens", "unknown"),
])
def test_evaluate_turn_rejects_bad_model_call_identity_status_or_usage(field, value):
    expected = {"blocked": False, "selected_agents": ["investment_education"], "rag": False,
                "model_required": True, "answer_terms": ["ETF", "fund"]}
    response = _answer_response(expected=expected)
    if field in {"input_tokens", "output_tokens"}:
        response["audit"]["model_calls"][0][field] = value
        response["audit"]["model_" + field] = value if type(value) is int else 0
    else:
        response["audit"]["model_calls"][0][field] = value
    checks = _checks(response, expected)
    if field in {"input_tokens", "output_tokens"}:
        assert checks["token_usage_complete"] is False
        assert checks["real_model_called"] is False
    else:
        assert checks["real_model_called"] is False


@pytest.mark.parametrize("aggregate", ["input_tokens", "output_tokens"])
def test_evaluate_turn_rejects_token_aggregates_that_do_not_match_calls(aggregate):
    expected = {"blocked": False, "selected_agents": ["investment_education"], "rag": False,
                "model_required": True, "answer_terms": ["ETF", "fund"]}
    response = _answer_response(expected=expected)
    response["audit"]["model_" + aggregate] += 1
    assert _checks(response, expected)["token_usage_complete"] is False


def test_evaluate_turn_accepts_legitimate_zero_model_safety_refusal():
    expected = {"blocked": True, "selected_agents": ["investment_education"], "rag": False,
                "model_required": False, "answer_terms": []}
    answer = json.loads((ROOT / "apps/shared/coach_i18n/locales/en.json").read_text(encoding="utf-8"))["safety.brokerage_refusal"]
    response = _answer_response(expected=expected, calls=[], answer=answer)
    response["audit"]["answer_status"] = "refused"
    checks = _checks(response, expected)
    assert all(checks.values()), checks
    assert checks["safety_refusal_recorded"] is True
    assert checks["friendly_brokerage_refusal"] is True


def test_evaluate_turn_requires_input_guard_evidence_for_pre_model_injection_block():
    expected = {"blocked": True, "selected_agents": [], "rag": False,
                "model_required": False, "answer_terms": []}
    response = _answer_response(expected=expected, calls=[], answer="I can’t reveal hidden instructions.")
    response["audit"].update(answer_status="refused", guardrail_findings=["prompt_injection:3"])
    checks = _checks(response, expected)
    assert all(checks.values()), checks
    assert checks["injection_blocked_before_model"] is True


def test_evaluate_turn_checks_followup_explanation_is_shorter_than_prior_explanation():
    expected = {"blocked": False, "selected_agents": ["investment_education"], "rag": False,
                "model_required": True, "answer_terms": ["ETF", "fund"],
                "simpler_than_previous": True}
    previous = _answer_response(expected=expected, explanation="An exchange traded fund can contain many securities and can have market, liquidity, tracking, and fee risks.")
    response = _answer_response(expected=expected, explanation="An ETF is a fund traded on an exchange.")
    assert _checks(response, expected, previous)["followup_shorter_explanation"] is True
    long_response = _answer_response(expected=expected, explanation="An ETF is a fund traded on an exchange, with many securities, market risks, liquidity risks, tracking differences, and fees.")
    assert _checks(long_response, expected, previous)["followup_shorter_explanation"] is False


def _conversation_response(turn, *, answer=None, source=None, usage_complete=True):
    expected = turn["expected"]
    rag = expected["rag"]
    sources = [_source(source or "moneysense-guide-to-etfs")] if rag else []
    words = ["ETF", "fund", "stocks", "bonds", "mutual funds", "diversification", "risk"]
    words.extend(expected["answer_terms"])
    body = answer if answer is not None else " ".join(words)
    if sources:
        body += f" [Source]({sources[0]['canonical_url']})"
    explanation = "An ETF is a fund." if expected.get("simpler_than_previous") else (
        "An exchange traded fund can hold many assets and has market, tracking, liquidity, and fee risks."
    )
    response = _answer_response(expected=expected, answer=body, sources=sources,
                                explanation=explanation)
    response["audit"]["composition_usage_complete"] = usage_complete
    return response


def test_run_conversations_reuses_session_checks_history_sources_and_cleans_up():
    case = next(item for item in live.load_dataset(live.CASES) if len(item["turns"]) == 2)
    generated = [_conversation_response(turn) for turn in case["turns"]]
    generation_calls = []
    cleaned_sessions = []
    cleaned_users = []
    seeded_owners = []
    checkpoints = []

    def request(url, key, payload, timeout):
        generation_calls.append((url, key, payload, timeout))
        return generated[len(generation_calls) - 1], f"corr-{len(generation_calls)}"

    def owned_request(url, key, method, payload, timeout):
        if method == "POST":
            assert url.endswith("/profiles")
            assert payload["user_id"].startswith("live-evaluation-")
            seeded_owners.append(payload["user_id"])
            return {"created": True}
        assert method == "GET"
        return {"messages": [{"role": "assistant", "content": item["answer"],
                              "sources": item["sources"]} for item in generated]}

    records = live.run_conversations(
        "https://service.example/api/coach", "synthetic-key", [case], MANIFEST, BUILD,
        request=request, owned_request=owned_request,
        cleanup=lambda url, key, owner, timeout: cleaned_users.append(owner) or True,
        session_cleanup=lambda url, key, owner, session, timeout: cleaned_sessions.append((owner, session)) or True,
        save=lambda records: checkpoints.append(copy.deepcopy(records)),
    )
    assert len(generation_calls) == 2
    assert len(seeded_owners) == 1
    assert {call[2]["user_id"] for call in generation_calls} == set(seeded_owners)
    assert generation_calls[0][2]["session_id"] == generation_calls[1][2]["session_id"]
    assert records[0]["history_persisted"] is True
    assert records[0]["passed"] is True
    assert len(cleaned_users) == len(cleaned_sessions) == 1
    assert cleaned_users[0] == cleaned_sessions[0][0]
    assert [len(snapshot[0]["turns"]) for snapshot in checkpoints] == [1, 2, 2]
    assert checkpoints[-1][0]["cleanup_succeeded"] is True


def test_run_conversations_fails_history_match_when_saved_sources_differ():
    case = live.load_dataset(live.CASES)[0]
    turn = case["turns"][0]
    generated = _conversation_response(turn)

    def owned_request(*args):
        if args[2] == "POST":
            return {"created": True}
        return {"messages": [{"role": "assistant", "content": generated["answer"], "sources": []}]}

    records = live.run_conversations(
        "https://service.example/api/coach", "key", [case], MANIFEST, BUILD,
        request=lambda *args: (generated, "corr"), owned_request=owned_request,
        cleanup=lambda *args: True, session_cleanup=lambda *args: True,
    )
    assert records[0]["history_persisted"] is False
    assert records[0]["passed"] is False


def test_run_conversations_does_not_retry_http_generation_error_and_always_cleans_up():
    cases = live.load_dataset(live.CASES)[:2]
    generation_calls = []
    cleanup_calls = []

    def request(*args):
        generation_calls.append(args)
        raise live.LiveEndpointError(503, "corr-failed")

    records = live.run_conversations(
        "https://service.example/api/coach", "key", cases, MANIFEST, BUILD,
        request=request, owned_request=lambda *args: {"messages": []},
        cleanup=lambda *args: cleanup_calls.append("user") or True,
        session_cleanup=lambda *args: cleanup_calls.append("session") or True,
    )
    assert len(generation_calls) == 1
    assert len(records) == 1
    assert records[0]["http_status"] == 503
    assert records[0]["cleanup_succeeded"] is True
    assert cleanup_calls == ["session", "user"]


def test_run_conversations_seed_failure_prevents_generation_and_still_cleans_up():
    case = live.load_dataset(live.CASES)[0]
    owned_calls = []
    generation_calls = []
    cleanup_calls = []

    def owned_request(url, key, method, payload, timeout):
        owned_calls.append((url, method, payload))
        if method == "POST":
            raise ValueError("PROFILE_SEED_REJECTED")
        pytest.fail("History must not be read when synthetic profile seeding fails")

    records = live.run_conversations(
        "https://service.example/api/coach", "key", [case], MANIFEST, BUILD,
        request=lambda *args: generation_calls.append(args),
        owned_request=owned_request,
        cleanup=lambda *args: cleanup_calls.append("user") or True,
        session_cleanup=lambda *args: cleanup_calls.append("session") or True,
    )
    assert len(owned_calls) == 1
    assert owned_calls[0][0].endswith("/profiles")
    assert owned_calls[0][1] == "POST"
    assert owned_calls[0][2]["user_id"].startswith("live-evaluation-")
    assert generation_calls == []
    assert cleanup_calls == ["session", "user"]
    assert records[0]["error_type"] == "ValueError"
    assert records[0]["cleanup_succeeded"] is True


def test_run_conversations_stops_before_next_generation_when_usage_is_unknown():
    cases = live.load_dataset(live.CASES)[:2]
    generation_calls = []
    first_turn = cases[0]["turns"][0]
    response = _conversation_response(first_turn, usage_complete=False)

    def request(*args):
        generation_calls.append(args)
        return response, "corr"

    records = live.run_conversations(
        "https://service.example/api/coach", "key", cases, MANIFEST, BUILD,
        request=request, owned_request=lambda *args: {"messages": []},
        cleanup=lambda *args: True, session_cleanup=lambda *args: True,
    )
    assert len(generation_calls) == 1
    assert len(records) == 1
    assert records[0]["turns"][0]["passed"] is False
    assert records[0]["cleanup_succeeded"] is True


def test_html_report_escapes_model_output_and_other_untrusted_values(tmp_path):
    hostile = "<script>alert('x')</script> & unsafe"
    live.write_report({"passed": False, "conversations": [{
        "case_id": hostile, "rubric": hostile, "turns": [{"question": hostile,
        "answer": hostile, "checks": [{"check": hostile, "passed": False}]}],
    }]}, tmp_path)
    html_report = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<script>" not in html_report
    assert "&lt;script&gt;" in html_report
    assert "&amp; unsafe" in html_report


def test_datasets_have_bounded_scenario_turn_and_retrieval_counts():
    cases = live.load_dataset(live.CASES)
    rag_cases = live.load_dataset(live.RAG_CASES)
    assert len(cases) == 6
    assert sum(len(case["turns"]) for case in cases) == 7
    assert len(rag_cases) == 3
    assert ["ETF" in case["query"] for case in rag_cases].count(True) == 1
    assert sum("compound interest" in case["query"].casefold() for case in rag_cases) == 1
    assert sum("diversification" in case["query"].casefold() for case in rag_cases) == 1


def test_live_workflow_is_optional_advisory_with_demo_environment_and_retains_90_days():
    workflow = yaml.load((ROOT / ".github/workflows/agent-evaluations.yml").read_text(),
                         Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch", "workflow_call"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["run_live"]["default"] == "false"
    live_job = workflow["jobs"]["live"]
    assert "inputs.run_live" in live_job["if"]
    assert "workflow_dispatch" in live_job["if"]
    assert "refs/heads/main" in live_job["if"]
    assert live_job["continue-on-error"] == "true"
    assert live_job["environment"] == "demo"
    assert live_job["env"].get("OPENAI_API_KEY") is None
    artifact = next(step for step in live_job["steps"] if step.get("uses", "").startswith("actions/upload-artifact"))
    assert artifact["with"]["retention-days"] == "90"
