"""Apply reviewed claim replacements without regenerating unaffected prose."""

from copy import deepcopy
from itertools import pairwise

from pydantic import BaseModel, ConfigDict, Field

from app.core.schemas import AgentName
from app.models.gateway import ModelGatewayError


class ClaimReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_id: str = Field(pattern=r"^review_[1-6]$")
    replacement: str = Field(max_length=3000)


class ClaimCorrections(BaseModel):
    model_config = ConfigDict(extra="forbid")
    replacements: list[ClaimReplacement] = Field(min_length=1, max_length=6)


def located_issues(draft, issues):
    """Only independently located, nonoverlapping local defects use this path."""
    located = []
    for index, issue in enumerate(issues, 1):
        start, end = issue.get("claim_start"), issue.get("claim_end")
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(draft)
                or issue.get("action") == "complete"):
            return []
        located.append({**issue, "issue_id": f"review_{index}", "original_claim": draft[start:end]})
    ordered = sorted(located, key=lambda issue: issue["claim_start"])
    if any(left["claim_end"] > right["claim_start"] for left, right in pairwise(ordered)):
        return []
    # Whole-answer/completeness corrections retain the existing writer contract.
    return located if located and sum(i["claim_end"] - i["claim_start"] for i in located) < len(draft) else []


def correction_edits(decision, issues):
    values = {item.issue_id: item.replacement for item in decision.replacements}
    if len(values) != len(decision.replacements) or set(values) != {i["issue_id"] for i in issues}:
        raise ModelGatewayError("Return each supplied issue_id exactly once.", code="INVALID_STRUCTURED_RESPONSE",
                                component="claim_correction", validation_reason="CORRECTION_ISSUE_MISMATCH")
    edits = []
    for issue in issues:
        replacement = values[issue["issue_id"]]
        if not replacement.strip() and issue.get("action") != "remove_claim":
            raise ModelGatewayError("A qualification or grounded claim needs replacement text.",
                                    code="INVALID_STRUCTURED_RESPONSE", component="claim_correction",
                                    validation_reason="CORRECTION_EMPTY_REPLACEMENT")
        edits.append((issue["claim_start"], issue["claim_end"], replacement))
    return sorted(edits)


def apply_edits(text, edits, *, allow_empty=False):
    cursor, parts = 0, []
    for start, end, replacement in sorted(edits):
        if not cursor <= start < end <= len(text):
            raise ModelGatewayError("Correction ranges overlap or are outside the original answer.",
                                    code="INVALID_STRUCTURED_RESPONSE", component="claim_correction",
                                    validation_reason="CORRECTION_RANGE_INVALID")
        parts.extend((text[cursor:start], replacement))
        cursor = end
    parts.append(text[cursor:])
    answer = "".join(parts)
    if (not allow_empty and not answer.strip()) or len(answer) > 6000:
        raise ModelGatewayError("The corrected answer must retain substantive content within its size limit.",
                                code="INVALID_STRUCTURED_RESPONSE", component="claim_correction",
                                validation_reason="CORRECTION_ANSWER_INVALID")
    return answer


def _offset(point, edits, *, end=False):
    delta = 0
    for left, right, replacement in edits:
        if point <= left:
            break
        if point < right:
            return left + delta + (len(replacement) if end else 0)
        delta += len(replacement) - (right - left)
    return point + delta


def _presentation_edits(start, length, edits):
    """Clip paragraph removals to owned prose; never split a replacement."""
    end = start + length
    local = []
    for left, right, text in edits:
        if start <= left < right <= end:
            local.append((left - start, right - start, text))
        elif not text and left < end and right > start:
            local.append((max(left, start) - start, min(right, end) - start, ""))
    return local


def corrected_results(results, draft, edits):
    """Update presentation only; all sealed financial/source authority stays fixed."""
    updated = []
    for result in results:
        copy = result.model_copy(deep=True)
        original = result.summary
        if original and draft.count(original) == 1:
            start = draft.index(original)
            local = _presentation_edits(start, len(original), edits)
            if local:
                copy.summary = apply_edits(original, local, allow_empty=True)
                if result.agent == AgentName.INVESTMENT_EDUCATION:
                    copy.data = deepcopy(result.data)
                    copy.data["review_sections"] = [
                        {**section, "start": _offset(section["start"], local),
                         "end": _offset(section["end"], local, end=True)}
                        for section in result.data.get("review_sections", [])
                    ]
                    # Generated presentation may also be stored separately. Do
                    # not retain its rejected form or change source authority.
                    def repair_text(text, original=original, local=local):
                        if not isinstance(text, str) or not text or original.count(text) != 1:
                            return text
                        offset = original.index(text)
                        changes = _presentation_edits(offset, len(text), local)
                        return apply_edits(text, changes, allow_empty=True) if changes else text
                    copy.data["uncertainties"] = [value for t in result.data.get("uncertainties", []) if (value := repair_text(t))]
                    copy.data["general_knowledge"] = [
                        {**item, "text": text}
                        for item in result.data.get("general_knowledge", [])
                        if (text := repair_text(item.get("text")))
                    ]
                    result._education_grounding_snapshot.for_review(copy.data)
        updated.append(copy)
    return updated
