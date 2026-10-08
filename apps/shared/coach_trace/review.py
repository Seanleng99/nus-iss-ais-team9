"""Fixed explanations for validated review metadata; never render model prose."""

BLOCK_REASONS = frozenset({
    "request_guardrail", "generated_guardrail", "regulated_advice", "cross_user_data",
    "specialist_blocked", "policy_evidence_missing", "financial_language_unsafe",
    "output_check", "request_not_allowed", "model_review", "review_contract_unverified",
})
CATEGORIES = frozenset({
    "prohibited_request", "personal_advice", "return_guarantee", "privacy", "injection",
    "citation_attribution", "factual_qualification", "unverifiable_claim",
})
VALIDATION_REASONS = frozenset({
    "STRUCTURED_JSON_INVALID", "STRUCTURED_SCHEMA_INVALID", "REVIEW_CATEGORY_MISMATCH",
    "REVIEW_UNKNOWN_SECTION", "REVIEW_CLAIM_NOT_UNIQUE", "REVIEW_CLAIM_OFFSET_MISMATCH",
    "REVIEW_CLAIM_LOCATION_REQUIRED", "REVIEW_FOREIGN_EVIDENCE_REF", "REVIEW_INVALID_CLAIM_RANGE",
    "EDUCATION_PLAN_DUPLICATE_ID", "EDUCATION_PLAN_UNKNOWN_TOPIC",
    "EDUCATION_PLAN_INVALID_PUBLIC_QUESTION", "EDUCATION_PLAN_INVALID_QUERY_TERMS",
})
POLICY_CLAUSES = frozenset({
    "AB-01", "AB-02", "AB-03", "AB-04", "AB-05", "AB-06",
    "EV-01", "EV-02", "EV-03", "EV-04", "EV-05", "EV-06", "EV-07", "EV-08",
    "IS-01", "IS-02", "IS-03", "IS-04", "IS-05",
})


def review_metadata(data):
    """Keep only known codes and booleans when withholding an AgentResult."""
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, allowed in (("block_reasons", BLOCK_REASONS),
                         ("review_block_categories", CATEGORIES),
                         ("policy_clause_refs", POLICY_CLAUSES)):
        values = data.get(key)
        if isinstance(values, (list, tuple)):
            result[key] = list(dict.fromkeys(
                value for value in values[:20] if isinstance(value, str) and value in allowed
            ))
    value = data.get("validation_reason")
    if isinstance(value, str) and value in VALIDATION_REASONS:
        result["validation_reason"] = value
    for key in ("request_allowed", "answer_complete"):
        if type(data.get(key)) is bool:
            result[key] = data[key]
    return result


def reason_keys(data):
    """Interpret recorded verdict codes, without making a new safety decision."""
    safe = review_metadata(data)
    reasons = safe.get("block_reasons", [])
    # A technical failure says nothing about the rejected draft's factual safety.
    for reason in ("review_contract_unverified", "policy_evidence_missing"):
        if reason in reasons:
            return ["safety.reason." + reason]
    categories = safe.get("review_block_categories", [])
    if categories:
        return ["safety.reason." + category for category in categories[:3]]
    return ["safety.reason." + reason for reason in reasons[:3] if reason != "model_review"]
