"""Passage-level retrieval gate. This does not score generated answer correctness."""

import argparse
import json
from collections import defaultdict
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.investment_education import InvestmentEducationAgent
from app.core.config import Settings
from app.core.prompts import PromptCatalog
from app.core.schemas import AgentTask
from app.rag.local_documents import (
    DEFAULT_CORPUS_ROOT,
    LocalDocumentEducationRetriever,
    load_documents,
)
from app.rag.retriever import LocalEducationRetriever, create_education_retriever


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=15)


class EvidenceCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    family: str = Field(min_length=1)
    split: Literal["development", "holdout"]
    language: Literal["en", "zh"]
    question: str = Field(min_length=1)
    expected_status: Literal["grounded", "partial", "insufficient"]
    required_evidence: list[Evidence]
    answer_rubric: list[str] = Field(min_length=1)
    unanswered_topics: list[str]

    @model_validator(mode="after")
    def require_ground_truth(self):
        if (self.expected_status == "insufficient") == bool(self.required_evidence):
            raise ValueError("evidence requirements must match the expected status")
        if self.expected_status == "partial" and not self.unanswered_topics:
            raise ValueError("partial cases must specify their unanswered topics")
        return self


def normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def load_cases(path: Path, documents: dict[str, str]) -> list[EvidenceCase]:
    cases = [
        EvidenceCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("benchmark must contain unique cases")
    family_splits = defaultdict(set)
    for case in cases:
        family_splits[case.family.removeprefix("mixed-")].add(case.split)
        for evidence in case.required_evidence:
            if normalize(evidence.quote) not in normalize(documents.get(evidence.source_id, "")):
                raise ValueError(
                    f"Ground-truth passage is absent from the approved corpus: {case.id}"
                )
    if any(len(splits) > 1 for splits in family_splits.values()):
        raise ValueError("paraphrases of one family cannot cross development and holdout")
    return cases


class NoGeneration:
    def generate(self, **kwargs):
        raise AssertionError(
            "Retrieval evaluation must not use a simulated answer as quality evidence"
        )


def evaluate(cases: list[EvidenceCase], retriever) -> dict:
    if not cases:
        raise ValueError("cannot evaluate an empty dataset")
    # This frozen benchmark measures retrieval evidence alone, independent of
    # generated query interpretation or model-assisted answerability decisions.
    agent = InvestmentEducationAgent(
        NoGeneration(), PromptCatalog(), 0.1, 800, retriever, semantic_grounding=False,
    )
    results = []
    for case in cases:
        grounding = agent._ground(
            AgentTask(agent="investment_education", sanitized_message=case.question),
            case.question,
        )
        found = [
            any(
                context["source_id"] == evidence.source_id
                and normalize(evidence.quote) in normalize(context["text"])
                for context in grounding["contexts"]
            )
            for evidence in case.required_evidence
        ]
        status_ok = grounding["evidence_status"] == case.expected_status
        gaps_ok = set(grounding.get("unanswered_topics", [])) == set(case.unanswered_topics)
        results.append(
            {
                "id": case.id,
                "family": case.family,
                "split": case.split,
                "language": case.language,
                "expected_status": case.expected_status,
                "actual_status": grounding["evidence_status"],
                "passage_hits": sum(found),
                "passage_requirements": len(found),
                "scope_correct": status_ok and gaps_ok,
                "passed": status_ok and gaps_ok and all(found),
                "retrieved_source_ids": [context["source_id"] for context in grounding["contexts"]],
                "context_words": sum(
                    len(context["text"].split()) for context in grounding["contexts"]
                ),
            }
        )

    def rate(items):
        return sum(item["passed"] for item in items) / len(items) if items else None

    counts = sum(r["passage_requirements"] for r in results)
    by_language = {
        language: rate([r for r in results if r["language"] == language])
        for language in ("en", "zh")
    }
    by_status = {
        status: rate([r for r in results if r["expected_status"] == status])
        for status in ("grounded", "partial", "insufficient")
    }
    return {
        "measurement": "authored passage-retrieval and scope benchmark; not generated-answer quality",
        "cases": len(results),
        "passed_cases": sum(r["passed"] for r in results),
        "case_accuracy": rate(results),
        "passage_recall_at_3": sum(r["passage_hits"] for r in results) / counts if counts else None,
        "scope_accuracy": sum(r["scope_correct"] for r in results) / len(results),
        "by_language": by_language,
        "by_status": by_status,
        "generated_answer_quality": {"status": "not_measured", "target": 0.99},
        "results": results,
    }


def retrieval_gate_passed(report: dict) -> bool:
    rates = [
        report["case_accuracy"],
        report["passage_recall_at_3"],
        *report["by_language"].values(),
    ]
    rates += [value for value in report["by_status"].values() if value is not None]
    return (
        all(value is not None and value >= 0.99 for value in rates)
        and report["scope_accuracy"] == 1
        and max(item["context_words"] for item in report["results"]) <= 1_200
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--provider",
        choices=["local_fixture", "local_documents", "bedrock"],
        default="local_documents",
    )
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="all")
    args = parser.parse_args()
    manifest, docs = load_documents(
        DEFAULT_CORPUS_ROOT / "source_manifest.json", DEFAULT_CORPUS_ROOT / "documents"
    )
    cases = load_cases(args.dataset, {source.source_id: text for source, text in docs})
    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]
    if not cases:
        parser.error("selected benchmark split is empty")
    if args.provider == "bedrock":
        config = Settings(RAG_PROVIDER="bedrock")
        if config.education_corpus_version != manifest.corpus_version:
            parser.error("live corpus pin must match the benchmark manifest")
        retriever = create_education_retriever(config)
    else:
        retriever = (
            LocalEducationRetriever()
            if args.provider == "local_fixture"
            else LocalDocumentEducationRetriever()
        )
    report = evaluate(cases, retriever)
    report.update(
        {
            "dataset_sha256": sha256(args.dataset.read_bytes()).hexdigest(),
            "corpus_version": manifest.corpus_version,
            "provider": args.provider,
            "split": args.split,
        }
    )
    report["retrieval_gate_passed"] = retrieval_gate_passed(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    if not report["retrieval_gate_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
