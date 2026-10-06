"""Server-owned character ranges for independent review; never duplicate prose."""

from app.core.schemas import AgentName, AgentResult


def draft_review_sections(draft: str, message: str, results: list[AgentResult]) -> list[dict]:
    sections = [
        {"section_id": "draft", "agent": None, "field": "draft_answer",
         "start": 0, "end": len(draft), "provenance": "combined"},
        {"section_id": "request", "agent": None, "field": "message",
         "start": 0, "end": len(message), "provenance": "request"},
    ]
    for result in results:
        if not result.summary or result.summary not in draft:
            continue
        start = draft.index(result.summary)
        owner = result.agent.value
        sections.append({
            "section_id": owner, "agent": owner, "field": "draft_answer",
            "start": start, "end": start + len(result.summary), "provenance": "specialist",
        })
        if result.agent != AgentName.INVESTMENT_EDUCATION:
            continue
        for index, section in enumerate(result.data.get("review_sections", []), 1):
            # A range can describe only text within its original specialist.
            # Malformed presentation metadata never authorizes a repair.
            if not isinstance(section, dict):
                continue
            left, right = section.get("start"), section.get("end")
            if (type(left) is not int or type(right) is not int
                    or not 0 <= left < right <= len(result.summary)
                    or section.get("section_id") != f"education_{index}"
                    or section.get("provenance") not in {"retrieved", "model_knowledge", "topic_label", "limitation"}):
                continue
            sections.append({
                "section_id": section["section_id"], "agent": owner, "field": "draft_answer",
                "start": start + left, "end": start + right,
                "provenance": section["provenance"], "topic": section.get("topic"),
            })
    return sections
