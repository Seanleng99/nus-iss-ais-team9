import json

import pytest
from language_fixtures import language_case

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
            summary = language_case("v7_response_contract.summary")
            if self.correct and self.education_calls > 1:
                summary += f" [source:{source_id}]"
            return json.dumps({
                "summary": summary, "rationale": [language_case("v7_response_contract.generate")],
                "confidence": 0.8, "source_ids": [source_id], "uncertainties": [],
            }, ensure_ascii=False)
        return super().generate(**kwargs)


def test_v7_corrects_missing_summary_citation_and_preserves_chinese_through_review():
    gateway = CitationGateway()
    result = AgentOrchestrator(
        config=Settings(MODEL_PROVIDER="local_fixture", PROMPT_SET_VERSION="v7"),
        gateway=gateway,
    ).handle(
        CoachRequest(
            user_id="contract-test",
            session_id="citation-correction",
            message=language_case("v7_response_contract.result"),
            response_locale="zh-Hans",
            requested_agents=["investment_education"],
        )
    )
    assert not result.blocked
    assert (
        language_case(
            "v7_response_contract.test_v7_corrects_missing_summary_citation_and_preserves_chinese_through_review"
        )
        in result.answer
    )
    assert "](https://" in result.answer
    assert gateway.education_calls == 2
    assert not any(call["system_prompt"].startswith("PROMPT_ID: synthesizer") for call in gateway.calls)
    review = next(call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: risk_compliance"))
    assert (
        language_case(
            "v7_response_contract.test_v7_corrects_missing_summary_citation_and_preserves_chinese_through_review_2"
        )
        in review["user_prompt"]
    )
    assert (
        language_case(
            "v7_response_contract.test_v7_corrects_missing_summary_citation_and_preserves_chinese_through_review_3"
        )
        not in review["user_prompt"]
    )
    education = next(call for call in gateway.calls if call["system_prompt"].startswith("PROMPT_ID: agent_investment_education"))
    assert "Required output language for THIS request: Chinese" in education["system_prompt"]


def test_v7_fails_after_one_unsuccessful_citation_correction():
    gateway = CitationGateway(correct=False)
    agent = InvestmentEducationAgent(
        gateway, PromptCatalog("v7"), 0.35, 800, LocalEducationRetriever(),
    )
    with pytest.raises(ModelGatewayError) as error:
        agent.run_task(
            AgentTask(
                agent="investment_education",
                sanitized_message=language_case(
                    "v7_response_contract.test_v7_fails_after_one_unsuccessful_citation_correction"
                ),
                input_data={},
            )
        )
    assert error.value.code == "MISSING_CITATION"
    assert gateway.education_calls == 2
