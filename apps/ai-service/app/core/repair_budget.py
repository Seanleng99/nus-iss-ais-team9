"""Forecast the actual affected calls without reserving a full retry for every role."""

import json
from math import ceil

from app.core.telemetry import log_event


def repair_time_estimate(calls: list[dict], required: set[str], *, attempts: int = 2) -> float:
    """Forecast passes without changing the gateway's enforced resource limits.

    Use observed provider latency, including rejected contract responses. This
    is admission forecasting, not a new deadline or a guarantee about latency.
    An unseen role uses the slowest observed call in the same workflow.
    Local replacements reserve one pass; optional writer retries must fit before
    reserved review time. Legacy full regeneration retains two-pass forecasting.
    """
    log_event("VV entering ", "app.core.repair_budget", "repair_time_estimate")
    durations = {}
    for call in calls:
        duration = call.get("duration_ms")
        if call.get("status") == "completed" and isinstance(duration, (int, float)) and duration >= 0:
            component = call.get("component")
            durations[component] = max(durations.get(component, 0), duration / 1000)
    fallback = max(durations.values(), default=0)
    return attempts * sum(durations.get(component, fallback) for component in required)


def financial_repair_estimates(calls: list[dict], required: set[str], feedback: object, *, planned_calls=None) -> list[dict]:
    log_event("VV entering ", "app.core.repair_budget", "financial_repair_estimates")
    latest = {}
    for call in reversed(calls):
        if call.get("status") == "completed" and call.get("component") in required:
            latest.setdefault(call["component"], call)
    feedback_tokens = ceil(len(json.dumps(feedback, ensure_ascii=False).encode("utf-8")) / 3)
    estimates = []
    for component, planned in sorted((planned_calls or {}).items()):
        if component in required and component not in latest:
            inputs, outputs = planned["input_tokens"], planned["max_output_tokens"]
            estimates.append({"component": component, "input_tokens": inputs,
                "output_tokens": outputs, "max_output_tokens": outputs,
                "estimated_repair_tokens": inputs + outputs + feedback_tokens + ceil((inputs + outputs) / 4),
                "estimate_basis": "planned_prompt_byte_bound"})
    for component, call in sorted(latest.items()):
        inputs = int(call.get("input_tokens") or 0)
        output_limit = int(call.get("max_output_tokens") or 0)
        outputs = min(output_limit, max(512, int(call.get("output_tokens") or 0) * 3 // 2 + 128))
        # This admission forecast allows correction metadata and contract growth.
        # The gateway still enforces actual limits and rejects unknown usage and
        # overruns, including any bounded structured-response validation retry.
        contingency = ceil((inputs + outputs) / 4)
        estimates.append({"component": component, "input_tokens": inputs,
                          "output_tokens": outputs, "max_output_tokens": output_limit,
                          "estimated_repair_tokens": inputs + outputs + feedback_tokens + contingency})
    return estimates
