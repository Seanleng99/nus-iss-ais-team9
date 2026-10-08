from copy import deepcopy

import httpx
from streamlit.testing.v1 import AppTest

from client import BackendClient
from ui.trace_viewer import event_rows, model_calls_for, safe_details


def test_compliance_reason_codes_survive_viewer_without_exposing_unreviewed_prose():
    assert safe_details({
        "blocked": True, "block_reasons": ["model_review", "UNREVIEWED PRIVATE DRAFT"],
        "policy_note_count": 1, "policy_source_count": 3, "policy_corpus_version": "policy-v1",
        "policy_notes": ["Private reviewer explanation"], "draft_answer": "Private draft",
    }) == {
        "blocked": True, "block_reasons": ["model_review"],
        "policy_note_count": 1, "policy_source_count": 3, "policy_corpus_version": "policy-v1",
    }

TRACE = {
    "trace_id": "run-1",
    "session_id": "chat-1",
    "status": "completed",
    "blocked": False,
    "created_at": "2026-09-26T01:00:00Z",
    "finished_at": "2026-09-26T01:00:02Z",
    "selected_agents": ["budget"],
    "model_provider": "fixture",
    "model_id": "fixture-model",
    "prompt_set_version": "v6",
    "correlation_id": "request-1",
    "assistant_message_id": "message-1",
    "agent_results": [
        {"agent": "budget", "rationale": ["The saved income supports the baseline."]}
    ],
    "audit": {
        "routing_rationale": ["Budget planning fits this question."],
        "workflow_duration_ms": 2000,
        "durable_events": [
            {
                "event_id": "e1",
                "event_type": "task.started",
                "actor": "budget",
                "task_id": "task-1",
                "timestamp": "2026-09-26T01:00:00Z",
                "details": {"attempt": 1},
            },
            {
                "event_id": "e2",
                "event_type": "model.generation.started",
                "task_id": "task-1",
                "span_id": "span-1",
                "timestamp": "2026-09-26T01:00:01Z",
                "details": {"call_id": "call-1", "component": "budget", "attempt": 1},
            },
            {
                "event_id": "e3",
                "event_type": "model.generation.finished",
                "task_id": "task-1",
                "span_id": "span-1",
                "timestamp": "2026-09-26T01:00:02Z",
                "details": {
                    "call_id": "call-1",
                    "component": "budget",
                    "status": "completed",
                    "input_tokens": 20,
                    "output_tokens": 10,
                    "duration_ms": 1000,
                },
            },
        ],
        "dependency_edges": [
            {
                "requester_task_id": "task-1",
                "provider_task_id": "task-2",
                "capability": "education_context",
            }
        ],
        "retrieval_sources": [
            {"source_id": "education-1", "title": "Budget basics", "corpus_version": "v1"}
        ],
    },
}


def test_blocked_trace_shows_safe_reason_and_policy_provenance():
    trace = deepcopy(TRACE)
    trace.update(status="blocked", blocked=True)
    trace["audit"]["policy_sources"] = [{"source_id": "coach-evidence-policy", "title": "Evidence policy",
        "document_version": "2026-10-09", "checksum": "sha256:" + "a" * 64, "review_due_at": "2027-01-06"}]
    trace["audit"]["durable_events"].append({"event_type": "compliance.completed", "details": {
        "blocked": True, "block_reasons": ["model_review"], "review_block_categories": ["factual_qualification"],
        "policy_clause_refs": ["EV-03"], "policy_notes": ["PRIVATE REJECTED PROSE"]}})
    test = page(TraceClient(trace))
    assert not test.exception
    assert any("factual qualification" in str(item.value) for item in test.markdown)
    assert any("EV-03" in item.value for item in test.caption)
    assert any("coach-evidence-policy" in str(frame.value) for frame in test.dataframe)
    assert not any("PRIVATE REJECTED PROSE" in str(item.value) for item in test.markdown)


def test_failed_review_validation_reason_is_retained_in_model_view():
    trace = deepcopy(TRACE)
    trace["audit"]["durable_events"].append({"event_type": "model.decision.rejected", "details": {
        "call_id": "call-1", "error_code": "INVALID_STRUCTURED_RESPONSE",
        "validation_reason": "REVIEW_FOREIGN_EVIDENCE_REF", "exception_message": "PRIVATE"}})
    call = model_calls_for(trace)[0]
    assert call["validation_reason"] == "REVIEW_FOREIGN_EVIDENCE_REF"
    assert "PRIVATE" not in str(call)


class TraceClient:
    def __init__(self, trace=None):
        self.trace = deepcopy(trace or TRACE)
        self.fetches = []
        self.lists = []
        self.missing = False
        self.empty = False
        self.fail = False

    def list_traces(self, user_id, *, status=None, offset=0):
        self.lists.append((user_id, status, offset))
        if self.fail:
            raise httpx.ConnectError("private connection information")
        return {
            "items": []
            if self.empty
            else [
                {
                    "trace_id": self.trace["trace_id"],
                    "status": self.trace["status"],
                    "created_at": self.trace["created_at"],
                    "conversation_title": "A budget question",
                }
            ],
            "next_offset": 25 if offset == 0 else None,
        }

    def get_trace(self, user_id, trace_id):
        self.fetches.append((user_id, trace_id))
        return None if self.missing or user_id != "owner" else self.trace


def page(client=None, *, open_trace=True):
    test = AppTest.from_string("from ui.trace_viewer import trace_page\ntrace_page()")
    test.session_state["backend_client"] = client or TraceClient()
    test.session_state["active_user_id"] = "owner"
    if open_trace:
        test.session_state["coach_trace_target"] = {"user_id": "owner", "trace_id": "run-1"}
    return test.run(timeout=30)


def test_complete_trace_renders_decisions_timeline_and_dependencies():
    test = page()
    assert not test.exception
    assert [tab.label for tab in test.tabs] == [
        "Decisions & evidence",
        "Timeline",
        "Dependencies",
        "Model calls",
    ]
    assert any("Budget planning fits" in text.value for text in test.text)
    assert any("Completed" in item.value for item in test.success)
    assert [metric.value for metric in test.metric] == ["3", "1", "2.00 s"]
    assert len(test.get("graphviz_chart")) == 1
    assert test.session_state["backend_client"].fetches == [("owner", "run-1")]
    test.selectbox(key="coach-trace-component-run-1").select("budget").run()
    assert not test.exception


def test_calendar_scoped_routing_decisions_render_in_frontend_runtime():
    trace = deepcopy(TRACE)
    trace["audit"]["durable_events"].append({
        "event_type": "routing.override_applied",
        "actor": "orchestrator",
        "details": {
            "before": {
                "budget_scope": {"kind": "default"},
                "spending_scope": {"kind": "default"},
            },
            "after": {
                "budget_scope": {"kind": "periods", "periods": ["2026-10-01"]},
                "spending_scope": {
                    "kind": "range", "start": "2026-09-01", "end": "2026-10-01",
                },
                "rationale": "PRIVATE ROUTING PROSE",
            },
        },
    })
    test = page(TraceClient(trace))
    assert not test.exception
    decisions = test.dataframe[0].value
    assert decisions.iloc[0]["Decision"] == "Routing · override applied"
    assert '"periods": ["2026-10-01"]' in decisions.iloc[0]["After"]
    assert '"start": "2026-09-01"' in decisions.iloc[0]["After"]
    assert "PRIVATE ROUTING PROSE" not in str(test)
    assert len(test.get("graphviz_chart")) == 1


def test_recovery_assignments_issues_and_financial_denials_render_without_rejected_text():
    from ui.trace_viewer import decision_rows, review_rows
    trace = deepcopy(TRACE)
    trace.update(status="blocked", blocked=True)
    trace["audit"]["durable_events"].extend([
        {"event_type": "routing.completed", "actor": "router", "details": {
            "task_assignments": [{"agent": "budget", "requires_spending": False,
                                  "question": "PRIVATE", "source_quotes": ["PRIVATE"]}]}},
        {"event_type": "compliance.completed", "actor": "risk_compliance", "details": {
            "review_round": 1, "blocked": True, "review_issues": [{
                "issue_id": "review_1", "section_id": "spending", "owner": "spending", "action": "qualify",
                "requirement_hash": "a" * 64, "evidence_refs": ["spending.category_totals"], "requirement": "PRIVATE"}]}},
        {"event_type": "financial.review.repair_decision", "actor": "orchestrator", "details": {
            "allowed": False, "repair_blockers": ["REPAIR_TOKEN_BUDGET_EXCEEDED"],
            "reason_code": "REPAIR_TOKEN_BUDGET_EXCEEDED", "draft_answer": "PRIVATE"}},
    ])
    decisions = decision_rows(trace)
    assert any('"requires_spending": false' in (row["Assigned requirements"] or "") for row in decisions)
    reviews = review_rows(trace)
    assert any(row.get("review_issues", [{}])[0].get("owner") == "spending" for row in reviews)
    assert any("REPAIR_TOKEN_BUDGET_EXCEEDED" in row.get("repair_blockers", []) for row in reviews)
    assert "PRIVATE" not in str(decisions + reviews)
    test = page(TraceClient(trace))
    assert not test.exception and "PRIVATE" not in str(test)


def test_failed_run_reconstructs_unfinished_model_calls():
    trace = deepcopy(TRACE)
    trace.update(status="timed_out", error_code="AI_SERVICE_TIMEOUT", assistant_message_id=None)
    trace["audit"]["durable_events"].pop()
    trace["audit"].pop("routing_rationale")
    trace["agent_results"] = []
    test = page(TraceClient(trace))
    assert not test.exception
    assert any("Timed out" in item.value for item in test.error)
    assert any("No final explanation" in item.value for item in test.info)
    assert model_calls_for(trace)[0]["status"] == "running"
    assert model_calls_for(trace)[0]["task_id"] == "task-1"


def test_blocked_trace_never_renders_withheld_explanations():
    trace = deepcopy(TRACE)
    trace.update(status="blocked", blocked=True)
    trace["audit"]["routing_rationale"] = ["WITHHELD_SECRET"]
    trace["agent_results"][0]["rationale"] = ["WITHHELD_SECRET"]
    trace["audit"]["retrieval_sources"][0]["title"] = "WITHHELD_SECRET"
    trace["audit"]["durable_events"][0]["details"]["prompt"] = "WITHHELD_SECRET"
    test = page(TraceClient(trace))
    assert not test.exception
    assert "WITHHELD_SECRET" not in str(test)
    assert any("withheld" in item.value for item in test.warning)


def test_selection_filters_pagination_and_refresh():
    test = page(open_trace=False)
    assert not test.tabs
    test.selectbox(key="coach_trace_owner_picker_all_0").select("run-1").run()
    assert not test.exception
    assert test.tabs
    test.button(key="coach_trace_owner_next").click().run()
    assert test.session_state["backend_client"].lists[-1] == ("owner", None, 25)
    test.selectbox(key="coach_trace_owner_status").select("failed").run()
    assert test.session_state["backend_client"].lists[-1] == ("owner", "failed", 0)
    test.button(key="coach_trace_owner_refresh").click().run()
    assert not test.exception


def test_reference_lookup_missing_profile_switch_and_empty_state():
    test = page(open_trace=False)
    test.text_input[0].input("run-1")
    test.button(key="FormSubmitter:coach_trace_owner_lookup-Open trace").click().run()
    assert test.tabs
    test.session_state["backend_client"].missing = True
    test.run()
    assert not test.tabs
    assert any("unavailable for the active profile" in item.value for item in test.warning)
    test.session_state["active_user_id"] = "another-owner"
    test.session_state["coach_trace_target"] = {"user_id": "owner", "trace_id": "run-1"}
    test.run()
    assert not test.tabs
    assert all(owner == "owner" for owner, _ in test.session_state["backend_client"].fetches)
    test.session_state["backend_client"].empty = True
    test.run()
    assert any("No runs match" in item.value for item in test.info)


def test_outage_clears_previously_displayed_trace():
    test = page()
    test.session_state["backend_client"].fail = True
    test.run()
    assert not test.tabs
    assert test.error
    assert "private connection information" not in str(test)


def test_legacy_events_and_unknown_metrics_are_supported():
    trace = deepcopy(TRACE)
    trace["audit"] = {
        "events": [
            {
                "event_type": "routing.completed",
                "occurred_at": "2026-09-26T01:00:00Z",
                "details": {"selected_agents": ["budget"]},
            }
        ]
    }
    test = page(TraceClient(trace))
    assert not test.exception
    assert any("Legacy trace" in item.value for item in test.caption)
    assert test.metric[2].value == "Not recorded"
    assert event_rows(trace["audit"]["events"])[0]["Time (SGT)"] == "26 Sep 2026, 09:00:00 SGT"


def test_trace_client_uses_authorized_query_parameters_and_safe_routes(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="service")
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    client = BackendClient(id_token="identity-token", transport=httpx.MockTransport(respond))
    client.list_traces("private-owner", status="failed", offset=25)
    client.get_trace("private-owner", "private-trace")
    assert dict(requests[0].url.params) == {
        "user_id": "private-owner",
        "offset": "25",
        "limit": "25",
        "status": "failed",
    }
    assert requests[1].url.params["user_id"] == "private-owner"
    assert all(request.headers["Authorization"] == "Bearer identity-token" for request in requests)
    assert "private-owner" not in caplog.text
    assert "private-trace" not in caplog.text


def test_saved_answer_links_to_the_active_profiles_trace():
    test = AppTest.from_string(
        "from ui.pages import _render_coach_explanation\n"
        "_render_coach_explanation({'trace_id': 'run-1', 'blocked': True})"
    )
    test.session_state["active_user_id"] = "owner"
    test.run()
    test.button(key="coach-open-trace-run-1").click().run()
    assert not test.exception
    assert test.session_state["coach_trace_target"] == {"user_id": "owner", "trace_id": "run-1"}
    assert test.query_params["page"] == ["traces"]


def test_failed_run_graph_reviews_and_coverage_use_only_saved_safe_events():
    from ui.trace_viewer import (
        coverage_rows,
        decision_rows,
        dependency_edges,
        dependency_resolutions,
        review_rows,
        task_rows,
    )

    trace = {"status": "failed", "audit": {"durable_events": [
        {"event_type": "routing.override_applied", "details": {"rule_id": "FOLLOW_UP_READ_ONLY",
         "before": {"budget_capture": True, "rationale": "PRIVATE"}, "after": {"budget_capture": False}}},
        {"event_type": "dependency.requested", "task_id": "requester", "details": {
         "request_id": "dep-1", "capability": "budget_capacity", "required": False}},
        {"event_type": "dependency.scheduled", "task_id": "requester", "parent_task_id": "provider", "details": {
         "request_id": "dep-1", "capability": "budget_capacity"}},
        {"event_type": "compliance.completed", "details": {"review_round": 1, "blocked": True,
         "review_block_categories": ["unverifiable_claim"], "policy_notes": ["PRIVATE"]}},
        {"event_type": "task.attempt.failed", "task_id": "provider", "details": {"error_code": "UNEXPECTED_AGENT_ERROR", "retryable": False}},
        {"event_type": "education.question.coverage", "details": {"question_id": "q1",
         "coverage_status": "partial", "source_ids": ["approved-source"], "passage_ids": ["p1"], "quote": "PRIVATE"}},
    ]}}
    assert dependency_edges(trace) == [{"Requester task": "requester", "Provider task": "provider", "Capability": "budget_capacity"}]
    assert dependency_resolutions(trace)[0]["required"] is False
    assert task_rows(trace)[0]["Outcome"] == "waiting_for_dependency"
    assert task_rows(trace)[1]["Outcome"] == "attempt_failed"
    assert review_rows(trace)[0]["review_block_categories"] == ["unverifiable_claim"]
    assert coverage_rows(trace)[0]["Coverage"] == "partial"
    assert "PRIVATE" not in str(decision_rows(trace) + review_rows(trace) + coverage_rows(trace))
    test = page(TraceClient({**TRACE, **trace}))
    assert not test.exception
    assert len(test.get("graphviz_chart")) == 1


def test_generation_success_and_rejected_decision_are_distinct_in_model_view():
    trace = deepcopy(TRACE)
    trace["audit"]["durable_events"].extend([
        {"event_type": "model.contract.validated", "span_id": "validation-span", "details": {"call_id": "call-1"}},
        {"event_type": "model.decision.rejected", "details": {"call_id": "call-1", "error_code": "MISSING_CITATION"}},
        {"event_type": "model.correction.requested", "span_id": "correction-span", "details": {"correction_of_call_id": "call-1", "attempt": 2}},
    ])
    call = model_calls_for(trace)[0]
    assert call["status"] == "completed"
    assert call["contract_status"] == "validated"
    assert call["decision_status"] == "rejected"
    assert call["correction_requested"]
    assert call["attempt"] == 1
    assert call["span_id"] == "span-1"


def test_model_contract_rejection_does_not_rewrite_generation_success():
    trace = deepcopy(TRACE)
    trace["audit"]["durable_events"].append({
        "event_type": "model.contract.rejected", "details": {"call_id": "call-1", "error_code": "INVALID_STRUCTURED_RESPONSE"},
    })
    call = model_calls_for(trace)[0]
    assert call["status"] == "completed"
    assert call["contract_status"] == "rejected"
