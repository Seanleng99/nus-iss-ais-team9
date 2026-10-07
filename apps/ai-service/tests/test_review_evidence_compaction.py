"""Save review tokens without removing independent claims or distinct evidence."""

import json

from app.agents.risk_compliance import RiskComplianceAgent
from app.core.citations import compact_evidence
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentResult, CoachRequest
from app.models.gateway import LocalFixtureModelGateway
from app.rag.policy import LocalPolicyRetriever


def test_compaction_removes_exact_duplicates_and_preserves_complete_distinct_passages():
    qualification = "Coverage applies only to the stated account and period.\n" * 150
    distinct = "A second passage supplies a different qualification."
    source = {"source_id": "source-a", "title": "A source", "document_version": "v1"}
    data = {
        "contexts": [{"source_id": "source-a", "text": qualification}] * 2
        + [{"source_id": "source-a", "text": distinct}, {"source_id": "unused", "text": "Uncited"}],
        "sources": [source, source, {**source, "document_version": "v2"}],
        "cited_source_ids": ["source-a"],
    }
    compacted = compact_evidence(data)
    assert compacted["contexts"] == [{"source_id": "source-a", "text": qualification},
                                     {"source_id": "source-a", "text": distinct}]
    assert [item["document_version"] for item in compacted["sources"]] == ["v1", "v2"]
    assert len(data["contexts"]) == 4 and len(data["sources"]) == 3


def test_multi_specialist_review_elides_only_summary_text_already_present_in_draft():
    class RecordingGateway(LocalFixtureModelGateway):
        def __init__(self):
            self.payload = None

        def generate(self, **kwargs):
            self.payload = json.loads(kwargs["user_prompt"])
            return super().generate(**kwargs)

    gateway = RecordingGateway()
    results = [AgentResult(agent="budget", summary="A budget groups planned expenses."),
               AgentResult(agent="goal_strategy", summary="A goal names a savings target."),
               AgentResult(agent="spending", summary="This caveat appears only in the specialist.")]
    draft = results[0].summary + "\n\n" + results[1].summary
    verdict = RiskComplianceAgent(gateway=gateway, prompts=PromptCatalog(), temperature=0,
                                  max_tokens=800, policy_retriever=LocalPolicyRetriever()).validate(
        CoachRequest(user_id="review-test", session_id="review-test", message="Discuss budgeting methods and savings goals."),
        results, draft)
    assert not verdict.blocked
    assert gateway.payload["draft_answer"] == draft
    assert [item["summary"] for item in gateway.payload["agent_results"]] == [
        "Same as draft_answer above.", "Same as draft_answer above.", results[2].summary]
    assert gateway.payload["policy_context"] == [
        {"source_id": item["source_id"], "text": item["text"]}
        for item in verdict.data["policy_contexts"]]


def test_coverage_quotes_reference_complete_passages_without_mutating_audit_evidence():
    quote = "Diversification spreads risk."
    text = quote + " It does not eliminate losses or guarantee returns."
    support = {"source_id": "source-a", "quote": quote, "evidence_field": "text", "passage_id": "p1"}
    question = {"question_id": "q1", "status": "partial", "limitation": "Personal affordability is not assessed.",
                "supporting_passages": [support]}
    data = {"contexts": [{"source_id": "source-a", "text": text}], "subquestion_coverage": [question]}
    compacted = compact_evidence(data)
    carried = compacted["subquestion_coverage"][0]["supporting_passages"][0]
    ref = carried["quote_ref"]
    assert compacted["contexts"][ref["context_index"]]["text"][ref["start"]:ref["end"]] == quote
    assert "quote" not in carried
    assert compacted["contexts"][0]["text"] == text
    assert compacted["subquestion_coverage"][0]["limitation"] == question["limitation"]
    assert support["quote"] == quote and "quote_ref" not in support


def test_quote_compaction_never_hides_unmatched_or_metadata_evidence():
    supports = [{"source_id": "source-b", "quote": "Absent source evidence."},
                {"source_id": "source-a", "quote": "A changed claim absent from the passage."},
                {"source_id": "source-a", "quote": "Saved guide", "evidence_field": "title"}]
    data = {"contexts": [{"source_id": "source-a", "text": "The original passage."}],
            "subquestion_coverage": [{"supporting_passages": supports}]}
    assert compact_evidence(data)["subquestion_coverage"][0]["supporting_passages"] == supports
