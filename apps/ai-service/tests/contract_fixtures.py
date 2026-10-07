"""Explicit current-contract adapters for scripted regression verdicts."""


def task_assignments(agents, message, education_topics=()):
    # These fixtures deliberately assign the supplied synthetic question. Tests
    # of semantic splitting provide their own distinct attributed assignments.
    return [
        {
            "agent": agent,
            "question": message,
            "source_quotes": [message],
            "education_topics": list(education_topics) if agent == "investment_education" else [],
            "requires_spending": False,
            "requires_capacity": True if agent == "goal_strategy" else None,
        }
        for agent in agents
    ]


def scoped_verdict(value, *, section="investment_education"):
    """Turn explicit old test requirements into section-specific review issues."""
    value = dict(value)
    value.setdefault("financial_language_safe", True)
    value.pop("repairable", None)  # Eligibility is derived by the server.
    points = value.get("missing_points", [])
    if "blocking_issues" not in value:
        veto = value.get("blocked") or not value.get("request_allowed", True)
        requirements = points or (["Correct the identified policy defect."] if veto else [])
        owner = "request" if not value.get("request_allowed", True) else section
        value["blocking_issues"] = [
            {"section_id": owner, "requirement": point} for point in requirements
        ]
    if value.get("complete"):
        value["missing_points"] = []
    return value
