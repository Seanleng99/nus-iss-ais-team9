"""Validate model edits against independently reviewed, server-owned text ranges."""

from difflib import SequenceMatcher

from app.core.telemetry import log_event
from app.models.gateway import ModelGatewayError


def validate_text_corrections(original: str, corrected: str, ranges: list[tuple[int, int]]) -> None:
    log_event("VV entering ", "app.core.narrative_corrections", "validate_text_corrections")
    if not ranges:
        return
    for tag, start, end, _, _ in SequenceMatcher(None, original, corrected, autojunk=False).get_opcodes():
        if tag != "equal" and not any(left <= start <= end <= right for left, right in ranges):
            raise ModelGatewayError(
                "Correct only the identified claim ranges; preserve all text outside them exactly.",
                code="INVALID_STRUCTURED_RESPONSE", component="financial_narrative_repair",
                validation_reason="CORRECTION_OUTSIDE_RANGE",
            )


def specialist_correction_ranges(corrections: list[dict], summary: str) -> list[tuple[int, int]]:
    log_event("VV entering ", "app.core.narrative_corrections", "specialist_correction_ranges")
    ranges = []
    for issue in corrections:
        start, end = issue.get("summary_claim_start"), issue.get("summary_claim_end")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(summary):
            return []  # Completeness without a claim location retains the existing bounded writer.
        ranges.append((start, end))
    return ranges
