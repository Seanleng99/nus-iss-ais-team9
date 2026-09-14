import json

import pytest

from app.agents.investment_education import InvestmentEducationAgent
from app.core.config import Settings
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentTask, CoachRequest
from app.models.gateway import LocalFixtureModelGateway, ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.retriever import LocalEducationRetriever


class CitationGateway(LocalFixtureModelGateway):
    def __init__(self, *, correct=True):
        self.correct = correct
        self.calls = []
        self.education_calls = 0

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["system_prompt"].startswith("PROMPT_ID: agent_investment_education"):
            self.education_calls += 1
            payload = json.loads(kwargs["user_prompt"])
            source_id = payload["grounding"]["sources"][0]["source_id"]
            summary = "分散投资可减少集中风险，但仍可能亏损。"
            if self.correct and self.education_calls > 1:
                summary += f" [source:{source_id}]"
            return json.dumps({
                "summary": summary, "rationale": ["解释依据提供的教育资料。"],
                "confidence": 0.8, "source_ids": [source_id], "uncertainties": [],
            }, ensure_ascii=False)
        return super().generate(**kwargs)


def test_v7_corrects_missing_summary_citation_and_preserves_chinese_through_review():
    gateway = CitationGateway()
    result = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", PROMPT_SET_VERSION="v7"),
        gateway=gateway,
    ).handle(CoachRequest(
        user_id="contract-test", session_id="citation-correction",
        message="解释分散投资", requested_agents=["investment_education"],
    ))
    assert not result.blocked
    assert "分散投资可减少集中风险" in result.answer
    assert "](https://" in result.answer
    assert gateway.education_calls == 2
    assert not any(call["system_prompt"].startswith("PROMPT_ID: synthesizer") for call in gateway.calls)
    review = next(call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: risk_compliance"))
    assert "分散投资可减少集中风险" in review["user_prompt"]
    assert "\\u5206" not in review["user_prompt"]
    education = next(call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: agent_investment_education"))
    assert "Required output language for THIS request: Chinese" in education["system_prompt"]


def test_v7_fails_after_one_unsuccessful_citation_correction():
    gateway = CitationGateway(correct=False)
    agent = InvestmentEducationAgent(
        gateway, PromptCatalog("v7"), 0.35, 800, LocalEducationRetriever(),
    )
    with pytest.raises(ModelGatewayError) as error:
        agent.run_task(AgentTask(
            agent="investment_education", sanitized_message="解释分散投资", input_data={},
        ))
    assert error.value.code == "MISSING_CITATION"
    assert gateway.education_calls == 2
