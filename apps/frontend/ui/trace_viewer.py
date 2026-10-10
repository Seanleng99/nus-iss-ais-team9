"""Profile-authorized decision trace browsing; retain only selections in UI state."""

import json
import re
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import streamlit as st
from coach_i18n import translate
from coach_trace import safe_details
from coach_trace.review import reason_keys

from ui.coach_language import current_selection
from ui.components import backend_call, page_header
from ui.i18n import display_frame, text_formatter, ui_text
from ui.state import get_client, get_user_id
from ui.telemetry import log_event

STATUSES = {
    "running": "Running",
    "completed": "Completed",
    "blocked": "Blocked",
    "failed": "Failed",
    "timed_out": "Timed out",
    "abandoned": "Abandoned",
}


def label(value):
    log_event("VV entering ", "ui.trace_viewer", "label")
    return str(value or "Unknown").replace("_", " ").replace(".", " · ").capitalize()


def timestamp(value):
    log_event("VV entering ", "ui.trace_viewer", "timestamp")
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def local_time(value):
    log_event("VV entering ", "ui.trace_viewer", "local_time")
    parsed = timestamp(value)
    return (
        parsed.astimezone(ZoneInfo("Asia/Singapore")).strftime("%d %b %Y, %H:%M:%S SGT")
        if parsed
        else ui_text("Not recorded")
    )


def events_for(trace):
    log_event("VV entering ", "ui.trace_viewer", "events_for")
    audit = trace.get("audit", {})
    events = audit.get("durable_events")
    if events is None:
        events = audit.get("events", [])
    return [item for item in events if isinstance(item, dict)]


def event_rows(events):
    log_event("VV entering ", "ui.trace_viewer", "event_rows")
    times = [timestamp(e.get("timestamp") or e.get("occurred_at")) for e in events]
    origin = min((value for value in times if value is not None), default=None)
    rows = []
    for index, (event, occurred) in enumerate(zip(events, times, strict=True)):
        details = safe_details(event.get("details"))
        rows.append(
            {
                "Step": index + 1,
                "Time (SGT)": local_time(event.get("timestamp") or event.get("occurred_at")),
                "Elapsed (s)": round((occurred - origin).total_seconds(), 3)
                if occurred and origin
                else None,
                "Event": label(event.get("event_type")),
                "Component": event.get("actor") or details.get("component") or "orchestrator",
                "Task": event.get("task_id") or details.get("task_id") or "",
                "Attempt": details.get("attempt"),
                "Reason": details.get("reason_code") or details.get("error_code") or "",
            }
        )
    return rows


def model_calls_for(trace):
    """Merge start/finish events so failed and still-running calls are visible."""
    log_event("VV entering ", "ui.trace_viewer", "model_calls_for")
    calls = {}
    for index, call in enumerate(trace.get("audit", {}).get("model_calls", [])):
        calls[call.get("call_id") or f"legacy-{index + 1}"] = dict(call)
    for event in events_for(trace):
        kind = event.get("event_type", "")
        if not (
            kind.startswith(("model.generation.", "model.decision.", "model.contract."))
            or kind == "model.correction.requested"
        ):
            continue
        details = safe_details(event.get("details"))
        call_id = details.get("call_id") or details.get("correction_of_call_id")
        if not call_id:
            continue
        call = calls.setdefault(call_id, {"call_id": call_id})
        if kind != "model.correction.requested":
            call.update(details)
        if kind.startswith("model.generation."):
            for key in ("task_id", "span_id"):
                if event.get(key):
                    call[key] = event[key]
        if event["event_type"] == "model.generation.started":
            call.setdefault("status", "running")
        elif kind == "model.generation.finished":
            call["status"] = details.get("status", "unknown")
        elif kind.startswith("model.contract."):
            call["contract_status"] = kind.rsplit(".", 1)[-1]
        elif kind.startswith("model.decision."):
            call["decision_status"] = kind.rsplit(".", 1)[-1]
        elif kind == "model.correction.requested":
            call["correction_requested"] = True
    return list(calls.values())


def dependency_edges(trace):
    log_event("VV entering ", "ui.trace_viewer", "dependency_edges")
    edges = []
    seen = set()
    recorded = list(trace.get("audit", {}).get("dependency_edges", []))
    for event in events_for(trace):
        if event.get("event_type") not in {"dependency.scheduled", "dependency.resolved"}:
            continue
        details = safe_details(event.get("details"))
        recorded.append(
            {
                "requester_task_id": details.get("requester_task_id") or event.get("task_id"),
                "provider_task_id": details.get("provider_task_id") or event.get("parent_task_id"),
                "capability": details.get("capability"),
            }
        )
    for edge in recorded:
        key = (edge.get("requester_task_id"), edge.get("provider_task_id"), edge.get("capability"))
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            edges.append(
                {"Requester task": key[0], "Provider task": key[1], "Capability": key[2] or ""}
            )
    return edges


def decision_rows(trace):
    log_event("VV entering ", "ui.trace_viewer", "decision_rows")
    rows = []
    for event in events_for(trace):
        kind = event.get("event_type", "")
        if not (
            kind.startswith(
                (
                    "routing.",
                    "backend.handler.",
                    "backend.action.",
                    "backend.composition.",
                    "synthesis.",
                )
            )
        ):
            continue
        details = safe_details(event.get("details"))
        rows.append(
            {
                "Decision": label(kind),
                "Source": details.get("decision_source") or event.get("actor"),
                "Rule": details.get("rule_id"),
                "Phase": ui_text(label(details.get("phase"))) if details.get("phase") else None,
                "Reason": details.get("reason_code"),
                "Before": json.dumps(details["before"]) if "before" in details else None,
                "After": json.dumps(details["after"]) if "after" in details else None,
                "Assigned requirements": json.dumps(details["task_assignments"]) if "task_assignments" in details else None,
                "Outcome": details.get("action_status")
                or details.get("handler")
                or details.get("component")
                or ", ".join(details.get("selected_agents", [])),
            }
        )
    return rows


def task_rows(trace):
    log_event("VV entering ", "ui.trace_viewer", "task_rows")
    tasks = {}
    for event in events_for(trace):
        task_id = event.get("task_id")
        if not task_id or not (
            event.get("event_type", "").startswith("task.")
            or event.get("event_type") == "dependency.requested"
        ):
            continue
        details = safe_details(event.get("details"))
        row = tasks.setdefault(
            task_id, {"Task": task_id, "Agent": details.get("agent") or event.get("actor")}
        )
        kind = event["event_type"].removeprefix("task.")
        if kind == "dependency.requested":
            row["Outcome"] = "waiting_for_dependency"
        elif kind == "attempt.failed":
            row["Outcome"] = "attempt_failed"
        elif kind == "retry_scheduled":
            row["Outcome"] = "retry_pending"
        elif kind == "attempt.started":
            row["Outcome"] = "running"
        if kind in {
            "queued",
            "started",
            "completed",
            "failed",
            "timed_out",
            "needs_input",
            "resumed",
        }:
            row["Outcome"] = kind
        for key, title in (
            ("queue_duration_ms", "Queue (ms)"),
            ("execution_duration_ms", "Execution (ms)"),
            ("dependency_wait_ms", "Dependency wait (ms)"),
            ("backoff_duration_ms", "Backoff (ms)"),
            ("evidence_status", "Evidence"),
            ("reason_code", "Reason"),
            ("error_code", "Error"),
            ("missing_fields", "Missing fields"),
            ("attempts", "Attempts"),
            ("required", "Required"),
        ):
            if key in details:
                row[title] = details[key]
    return list(tasks.values())


def review_rows(trace):
    log_event("VV entering ", "ui.trace_viewer", "review_rows")
    return [
        {"Decision": label(event["event_type"]), **safe_details(event.get("details"))}
        for event in events_for(trace)
        if event.get("event_type")
        in {
            "compliance.started",
            "compliance.completed",
            "education.completeness.repair_decision",
            "education.completeness.repair",
            "education.completeness.repair_unavailable",
            "financial.review.repair_decision",
            "financial.review.repair_unavailable",
        }
    ]


def coverage_rows(trace):
    # Only final reviewed prose is displayed; unfinished/blocked runs use code-only events.
    log_event("VV entering ", "ui.trace_viewer", "coverage_rows")
    rows = []
    if not trace.get("blocked") and trace.get("status", "completed") == "completed":
        for result in trace.get("agent_results", []):
            if result.get("blocked"):
                continue
            data = result.get("data", {})
            questions = {q.get("question_id"): q for q in data.get("subquestions", [])}
            for coverage in data.get("subquestion_coverage", []):
                qid = coverage.get("question_id")
                question = questions.get(qid, {})
                for passage in coverage.get("supporting_passages") or [{}]:
                    rows.append(
                        {
                            "Question ID": qid,
                            "Question": question.get("public_question"),
                            "Coverage": coverage.get("status"),
                            "Source": passage.get("source_id"),
                            "Passage": passage.get("passage_id"),
                            "Supporting text": passage.get("quote"),
                            "Limitation": coverage.get("limitation"),
                        }
                    )
    if not rows:
        for event in events_for(trace):
            if event.get("event_type") == "education.question.coverage":
                details = safe_details(event.get("details"))
                rows.append(
                    {
                        "Question ID": details.get("question_id"),
                        "Coverage": details.get("coverage_status"),
                        "Source": ", ".join(details.get("source_ids", [])),
                        "Passage": ", ".join(details.get("passage_ids", [])),
                    }
                )
    return rows


def dependency_resolutions(trace):
    log_event("VV entering ", "ui.trace_viewer", "dependency_resolutions")
    requirements = {
        safe_details(e.get("details")).get("request_id"): safe_details(e.get("details")).get(
            "required"
        )
        for e in events_for(trace)
        if e.get("event_type") == "dependency.requested"
    }
    saved = [
        {**r, "required": requirements.get(r.get("request_id"))}
        for r in trace.get("audit", {}).get("dependency_resolutions", [])
    ]
    seen = {(r.get("request_id"), r.get("resolution")) for r in saved}
    for event in events_for(trace):
        if event.get("event_type") not in {
            "dependency.scheduled",
            "dependency.resolved",
            "dependency.rejected",
        }:
            continue
        details = safe_details(event.get("details"))
        resolution = details.get("resolution") or event["event_type"].rsplit(".", 1)[-1]
        key = (details.get("request_id"), resolution)
        if key not in seen:
            seen.add(key)
            saved.append(
                {
                    **details,
                    "resolution": resolution,
                    "required": requirements.get(details.get("request_id")),
                    "requester_task_id": details.get("requester_task_id") or event.get("task_id"),
                    "provider_task_id": details.get("provider_task_id")
                    or event.get("parent_task_id"),
                }
            )
    return saved


def render_trace(trace):
    log_event("VV entering ", "ui.trace_viewer", "render_trace")
    trace_id = trace["trace_id"]
    audit = trace.get("audit", {})
    status = "blocked" if trace.get("blocked") else trace.get("status", "completed")
    status_text = {
        "completed": "Completed — the final answer was saved.",
        "blocked": "Blocked — the safety review withheld the generated guidance.",
        "running": "Running — refresh to load the latest saved events.",
        "failed": "Failed — the run did not finish successfully. Saved events remain available.",
        "timed_out": "Timed out — the run exceeded its time limit. Saved events remain available.",
        "abandoned": "Abandoned — execution stopped or exceeded its recovery deadline.",
    }.get(status, "Run status unavailable.")
    display = (
        st.error
        if status in {"failed", "timed_out"}
        else st.warning
        if status in {"blocked", "abandoned"}
        else st.success
        if status == "completed"
        else st.info
    )
    display(ui_text(status_text))
    st.caption(ui_text("Reference ID: {v0}", v0=trace_id))
    events = events_for(trace)
    calls = model_calls_for(trace)
    first, second, third = st.columns(3)
    first.metric(ui_text("Recorded events"), len(events))
    second.metric(ui_text("Model calls"), len(calls))
    duration = audit.get("workflow_duration_ms")
    third.metric(
        ui_text("AI duration"),
        f"{duration / 1000:.2f} s"
        if isinstance(duration, (float, int))
        else ui_text("Not recorded"),
    )
    if trace.get("error_code"):
        st.caption(ui_text("Failure code: {v0}", v0=trace["error_code"]))
    st.caption(
        ui_text(
            "Started {v0} · Finished {v1}",
            v0=local_time(trace.get("created_at")),
            v1=local_time(trace.get("finished_at")),
        )
    )

    decisions, timeline, dependencies, models = st.tabs(
        [
            ui_text("Decisions & evidence"),
            ui_text("Timeline"),
            ui_text("Dependencies"),
            ui_text("Model calls"),
        ]
    )
    with decisions:
        for title, rows in (
            ("Decision summary", decision_rows(trace)),
            ("Agent outcomes", task_rows(trace)),
            ("Reviews and repairs", review_rows(trace)),
            ("Question coverage", coverage_rows(trace)),
        ):
            if rows:
                st.markdown(f"**{ui_text(title)}**")
                st.dataframe(display_frame(rows), hide_index=True, width="stretch")
        agents = trace.get("selected_agents", [])
        st.write(
            "Selected areas: " + (", ".join(label(agent) for agent in agents) or "None recorded")
        )
        if trace.get("blocked") or status == "blocked":
            st.info(
                ui_text(
                    "Generated explanations are withheld for this run. You can inspect execution metadata in the other tabs."
                )
            )
            last_review = next((event.get("details", {}) for event in reversed(events_for(trace))
                                if event.get("event_type") == "compliance.completed"), {})
            for key in reason_keys(last_review):
                st.write(translate(key, current_selection()))
            clauses = safe_details(last_review).get("policy_clause_refs", [])
            if clauses:
                st.caption(ui_text("Relevant policy clauses: {v0}", v0=", ".join(clauses)))
        else:
            rationales = audit.get("routing_rationale", [])
            if rationales:
                st.markdown(ui_text("**Why these agents were selected**"))
                for rationale in rationales:
                    st.text(rationale)
            results = trace.get("agent_results", [])
            for result in results:
                with st.expander(label(result.get("agent"))):
                    if result.get("blocked"):
                        st.info(ui_text("This agent's generated explanation was withheld."))
                        continue
                    for rationale in result.get("rationale", []):
                        st.text(rationale)
            if not rationales and not results:
                st.info(
                    ui_text(
                        "No final explanation was saved. The timeline shows the decisions recorded before execution stopped."
                    )
                )
        for title, key in (
            ("Education evidence", "retrieval_sources"),
            ("Policy evidence", "policy_sources"),
        ):
            sources = audit.get(key, [])
            if sources:
                st.markdown(f"**{ui_text(title)}**")
                st.dataframe(
                    display_frame([
                        {"Source": source.get("source_id"), "Title": source.get("title"),
                         "Version": source.get("document_version") or source.get("corpus_version"),
                         "Checksum": source.get("checksum"), "Review due": source.get("review_due_at")}
                        for source in sources
                    ]),
                    hide_index=True,
                )
        st.caption(
            ui_text(
                "These are recorded decisions and stated reasons. They do not expose hidden model reasoning."
            )
        )

    with timeline:
        if "durable_events" not in audit:
            st.caption(
                ui_text(
                    "Legacy trace: showing the final audit events; incremental history may be unavailable."
                )
            )
        if not events:
            st.info(ui_text("No events have been recorded for this run."))
        else:
            rows = event_rows(events)
            components = sorted({row["Component"] for row in rows})
            component = st.selectbox(
                ui_text("Component"),
                ["All components", *components],
                format_func=text_formatter(
                    {value: value for value in ["All components", *components]}
                ),
                key=f"coach-trace-component-{trace_id}",
            )
            visible = (
                rows
                if component == "All components"
                else [row for row in rows if row["Component"] == component]
            )
            tasks = sorted({row["Task"] for row in visible if row["Task"]})
            task = st.selectbox(
                ui_text("Task"),
                ["All tasks", *tasks],
                format_func=text_formatter({value: value for value in ["All tasks", *tasks]}),
                key=f"coach-trace-task-{trace_id}-{component}",
            )
            if task != "All tasks":
                visible = [row for row in visible if row["Task"] == task]
            st.dataframe(display_frame(visible), hide_index=True, width="stretch")
            st.caption(
                ui_text(
                    "Steps follow saved event order. Parallel tasks can overlap; task and parent IDs establish relationships."
                )
            )
            step = st.selectbox(
                ui_text("Inspect event"),
                [row["Step"] for row in visible],
                format_func=lambda n: f"{n} · {rows[n - 1]['Event']}",
                key=f"coach-trace-event-{trace_id}-{component}",
            )
            if step is not None:
                event = events[step - 1]
                with st.expander(ui_text("Event identifiers and metadata")):
                    st.json(
                        {
                            **{
                                key: event.get(key)
                                for key in (
                                    "event_id",
                                    "trace_id",
                                    "task_id",
                                    "parent_task_id",
                                    "span_id",
                                    "parent_span_id",
                                )
                                if event.get(key)
                            },
                            "details": safe_details(event.get("details")),
                        }
                    )
    with dependencies:
        edges = dependency_edges(trace)
        if edges:
            nodes = {row["Requester task"] for row in edges} | {
                row["Provider task"] for row in edges
            }
            names = {
                e.get("task_id"): label(e.get("actor"))
                for e in events
                if e.get("task_id") and e.get("actor")
            }
            dot = ["digraph dependencies { rankdir=LR; node [shape=box, style=rounded];"]
            for node in sorted(nodes):
                dot.append(
                    f"{json.dumps(node)} [label={json.dumps(names.get(node, 'Task') + chr(10) + node)}];"
                )
            for row in edges:
                dot.append(
                    f"{json.dumps(row['Requester task'])} -> {json.dumps(row['Provider task'])} [label={json.dumps(row['Capability'])}];"
                )
            st.graphviz_chart("\n".join([*dot, "}"]), width="stretch")
            st.caption(
                ui_text("Arrows point from the requesting task to the task providing a capability.")
            )
            st.dataframe(display_frame(edges), hide_index=True)
        else:
            st.info(
                ui_text(
                    "No dependency edges were saved. This does not prove that every task ran independently."
                )
            )
        resolutions = dependency_resolutions(trace)
        if resolutions:
            st.dataframe(
                display_frame(
                    [
                        {
                            "Capability": r.get("capability"),
                            "Required": r.get("required"),
                            "Resolution": r.get("resolution"),
                            "Requester": r.get("requester_task_id"),
                            "Provider": r.get("provider_task_id"),
                            "Reason": r.get("reason_code"),
                        }
                        for r in resolutions
                    ]
                ),
                hide_index=True,
            )
    with models:
        if not calls:
            st.info(
                ui_text(
                    "No model calls were recorded. The request may have stopped before a model was invoked."
                )
            )
        else:
            st.dataframe(
                display_frame(
                    [
                        {
                            "Component": c.get("component", "Unknown"),
                            "Status": c.get("status", "unknown"),
                            "Contract": c.get("contract_status"),
                            "Decision": c.get("decision_status"),
                            "Correction requested": c.get("correction_requested"),
                            "Attempt": c.get("attempt"),
                            "Duration (ms)": c.get("duration_ms"),
                            "Input tokens": c.get("input_tokens"),
                            "Output tokens": c.get("output_tokens"),
                            "Task ID": c.get("task_id"),
                            "Call ID": c.get("call_id"),
                            "Span ID": c.get("span_id"),
                            "Error": c.get("error_code"),
                            "Validation reason": c.get("validation_reason"),
                        }
                        for c in calls
                    ]
                ),
                hide_index=True,
            )
            st.caption(
                ui_text(
                    "Missing token counts are unknown, not zero. A call still marked running may have continued after the run ended."
                )
            )
    with st.expander(ui_text("Run metadata")):
        st.json(
            {
                key: trace.get(key)
                for key in (
                    "trace_id",
                    "correlation_id",
                    "session_id",
                    "assistant_message_id",
                    "model_provider",
                    "model_id",
                    "prompt_set_version",
                )
            }
        )


def trace_link(trace_id, locale="en"):
    log_event("VV entering ", "ui.trace_viewer", "trace_link")
    if trace_id and st.button(
        translate("coach.trace", locale),
        key=f"coach-open-trace-{trace_id}",
        icon=":material/account_tree:",
    ):
        st.session_state.coach_trace_target = {"user_id": get_user_id(), "trace_id": trace_id}
        st.query_params["page"] = "traces"
        st.rerun()


def trace_page():
    log_event("VV entering ", "ui.trace_viewer", "trace_page")
    client, user_id = get_client(), get_user_id()
    page_header(
        ui_text("Decision traces"),
        ui_text("Inspect saved decisions, evidence, and execution outcomes"),
    )
    prefix = f"coach_trace_{user_id}"
    offset_key, open_key = f"{prefix}_offset", f"{prefix}_open"
    target = st.session_state.pop("coach_trace_target", None)
    if target and target.get("user_id") == user_id:
        st.session_state[open_key] = target["trace_id"]

    def reset_list():
        log_event("VV entering ", "ui.trace_viewer", "trace_page.reset_list")
        st.session_state[offset_key] = 0
        st.session_state.pop(open_key, None)

    controls, refresh = st.columns([4, 1], vertical_alignment="bottom")
    status = controls.selectbox(
        ui_text("Run status"),
        ["all", *STATUSES],
        format_func=text_formatter({"all": "All statuses", **STATUSES}),
        key=f"{prefix}_status",
        on_change=reset_list,
    )
    refresh.button(ui_text("Refresh"), key=f"{prefix}_refresh", use_container_width=True)
    with st.expander(ui_text("Find by reference ID")), st.form(f"{prefix}_lookup"):
        trace_id = st.text_input(ui_text("Find by reference ID"), max_chars=128)
        if st.form_submit_button(ui_text("Open trace")):
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", trace_id.strip()):
                st.session_state[open_key] = trace_id.strip()
            else:
                st.warning(ui_text("Enter a valid reference ID."))
    offset = st.session_state.get(offset_key, 0)
    page = backend_call(
        lambda: client.list_traces(
            user_id, status=None if status == "all" else status, offset=offset
        )
    )
    if page is None:
        return
    items = page.get("items", [])
    if items:
        options = {item["trace_id"]: item for item in items}

        def choose():
            log_event("VV entering ", "ui.trace_viewer", "trace_page.choose")
            st.session_state[open_key] = st.session_state[picker_key]

        picker_key = f"{prefix}_picker_{status}_{offset}"
        current = st.session_state.get(open_key)
        # The selected ID is metadata only. Always reload its authorized record.
        st.session_state[picker_key] = current if current in options else None
        st.selectbox(
            ui_text("Recent runs"),
            list(options),
            index=None,
            placeholder=ui_text("Choose a run"),
            format_func=lambda id: (
                f"{STATUSES.get(options[id]['status'], 'Unknown')} · {local_time(options[id]['created_at'])} · {options[id]['conversation_title'][:70]} · {id[:8]}"
            ),
            key=picker_key,
            on_change=choose,
        )
    else:
        st.info(
            ui_text(
                "No runs match this filter. Traces appear after a coaching request and may expire under the retention policy."
            )
        )
    previous, next_page = st.columns(2)
    if previous.button(ui_text("Newer runs"), disabled=offset == 0, key=f"{prefix}_previous"):
        st.session_state[offset_key] = max(0, offset - 25)
        st.rerun()
    if next_page.button(
        ui_text("Older runs"), disabled=page.get("next_offset") is None, key=f"{prefix}_next"
    ):
        st.session_state[offset_key] = page["next_offset"]
        st.rerun()
    selected = st.session_state.get(open_key)
    if not selected:
        st.caption(ui_text("Choose a recent run or enter a reference ID to inspect it."))
        return
    trace = backend_call(lambda: client.get_trace(user_id, selected) or {"missing": True})
    if trace is None:
        return
    if trace.get("missing"):
        st.warning(
            ui_text(
                "This trace is unavailable for the active profile. It may have expired or been deleted."
            )
        )
        return
    st.divider()
    render_trace(trace)
