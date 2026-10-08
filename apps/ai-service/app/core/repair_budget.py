"""Forecast the actual affected calls without reserving a full retry for every role."""

import json
from math import ceil


def financial_repair_estimates(calls: list[dict], required: set[str], feedback: object, *, planned_calls=None) -> list[dict]:
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
