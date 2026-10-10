"""Final prose can vary; validated backend outcomes remain authoritative."""

from time import perf_counter

from coach_i18n import localize_backend_text, request_locale, response_language

from app.clients.ai_service import AIServiceUnavailableError
from app.core.run_trace import active_run, record_event
from app.core.telemetry import log_event


def action_outcome(operation, response):
    log_event("VV entering ", "app.services.response_composition", "action_outcome")
    status = response.audit.get("action_status", response.audit.get(f"{operation}_capture"))
    return {
        "operation": operation,
        "status": status[:80] if isinstance(status, str) and status else "reviewed_result",
        "text": response.answer,
        "authority": "authenticated_backend",
    }


async def compose_backend_response(client, request, response, outcomes=None):
    log_event("VV entering ", "app.services.response_composition", "compose_backend_response")
    if response.blocked:
        return response
    run = active_run.get()
    if run is not None:
        response.audit["trace_id"] = run.trace_id
    for outcome in outcomes or [action_outcome(str(response.audit.get("source", "backend_result"))[:80], response)]:
        record_event("backend.action.outcome", phase="pending_commit", operation=outcome["operation"], action_status=outcome["status"])
    record_event("backend.composition.started")
    response.audit.update(response_locale=request_locale(request), response_language=response_language(request),
                          reviewed_action_outcome=True)
    response.answer = localize_backend_text(response.answer, request_locale(request))
    outcomes = outcomes or [action_outcome(str(response.audit.get("source", "backend_result"))[:80], response)]
    response.audit["backend_outcomes"] = outcomes
    compose = getattr(client, "compose", None)
    if compose is None:
        response.audit["post_action_composed"] = False
        response.audit["composition_fallback_code"] = "COMPOSITION_CLIENT_UNAVAILABLE"
        record_event("backend.composition.fallback", reason_code="COMPOSITION_CLIENT_UNAVAILABLE")
        return response
    started = perf_counter()
    try:
        composed = await compose(request, response, outcomes)
        if (composed.blocked or composed.session_id != request.session_id
                or composed.selected_agents != response.selected_agents
                or composed.sources != response.sources
                or (response.audit.get("trace_id") and composed.audit.get("trace_id") != response.audit["trace_id"])):
            raise ValueError("Invalid composition identity or evidence")
        composed.audit["backend_outcomes"] = outcomes
        composed.audit["post_action_duration_ms"] = round((perf_counter() - started) * 1000, 2)
        record_event("backend.composition.completed", allowed=True,
                     status="composed" if composed.audit.get("post_action_composed") else "fallback",
                     reason_code=composed.audit.get("composition_fallback_code"))
        return composed
    except (AIServiceUnavailableError, ValueError, TypeError, AttributeError):
        # The private composition request may still consume provider calls
        # after transport failure. Preserve known prior usage, but do not claim
        # that it accounts for the attempted composition without validated audit.
        response.audit.update(post_action_composed=False, composition_fallback_code="COMPOSITION_UNAVAILABLE",
                              composition_usage_complete=False)
        record_event("backend.composition.fallback", reason_code="COMPOSITION_UNAVAILABLE")
        return response
    finally:
        response.audit["post_action_duration_ms"] = round((perf_counter() - started) * 1000, 2)
