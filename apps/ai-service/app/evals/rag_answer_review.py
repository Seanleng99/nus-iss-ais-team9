"""Capture real Bedrock answers and enforce a complete, explicitly scored review."""

import argparse
import json
import re
from hashlib import sha256
from pathlib import Path

from app.core.config import Settings
from app.core.schemas import CoachRequest
from app.evals.rag_evidence import load_cases
from app.models.gateway import ModelGatewayError
from app.orchestrator import AgentOrchestrator
from app.rag.local_documents import DEFAULT_CORPUS_ROOT, load_documents
from app.rag.retriever import RetrievalError

REVIEW_FIELDS = (
    "grounded",
    "complete",
    "safe",
    "citations_supported",
    "language_correct",
    "gap_correct",
)


def response_digest(response: dict) -> str:
    return sha256(json.dumps(response, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def capture(cases, config: Settings, dataset_digest: str, output: Path, repeats: int):
    if any(
        provider != "bedrock"
        for provider in (
            config.model_provider,
            config.rag_provider,
            config.policy_rag_provider,
        )
    ):
        raise ValueError(
            "Answer-quality evidence requires real Bedrock generation and both managed retrievers"
        )
    if not 1 <= repeats <= 5:
        raise ValueError("repeats must be between 1 and 5")
    orchestrator = AgentOrchestrator(config=config)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves earlier successes and failures as separate evidence.
    with output.open("x", encoding="utf-8") as handle:
        for case in cases:
            for repeat in range(repeats):
                row = {
                    "case_id": case.id,
                    "repeat": repeat,
                    "dataset_sha256": dataset_digest,
                    "providers": {
                        "model": config.model_provider,
                        "education": config.rag_provider,
                        "policy": config.policy_rag_provider,
                    },
                    "question": case.question,
                    "required_evidence": [e.model_dump() for e in case.required_evidence],
                    "answer_rubric": case.answer_rubric,
                    "expected_status": case.expected_status,
                    "unanswered_topics": case.unanswered_topics,
                    "reviewer": "",
                    "reviewed_response_sha256": "",
                    "review": dict.fromkeys(REVIEW_FIELDS),
                }
                try:
                    response = orchestrator.handle(
                        CoachRequest(
                            user_id="eval-synthetic-rag-quality",
                            session_id=f"{case.id}-{repeat}",
                            message=case.question,
                            requested_agents=["investment_education"],
                        )
                    ).model_dump(mode="json")
                    row.update(
                        response=response, response_sha256=response_digest(response), error=None
                    )
                except (ModelGatewayError, RetrievalError, ValueError, TimeoutError) as exc:
                    # Provider messages can contain request details; retain only a bounded code.
                    row.update(response=None, response_sha256=None, error=type(exc).__name__)
                    code = getattr(exc, "code", "")
                    row["error_code"] = code if re.fullmatch(r"[A-Z0-9_]{1,80}", code) else None
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()


def score_reviews(
    rows: list[dict], cases, dataset_digest: str, corpus_version: str, repeats: int = 3,
    expected_model_id: str = "apac.amazon.nova-lite-v1:0",
) -> dict:
    if not cases or not 1 <= repeats <= 5:
        raise ValueError("A nonempty benchmark and 1–5 repeats are required")
    expected = {(case.id, repeat) for case in cases for repeat in range(repeats)}
    keys = [(row.get("case_id"), row.get("repeat")) for row in rows]
    if len(keys) != len(set(keys)) or set(keys) != expected:
        raise ValueError(
            "Review must include every expected case/repeat exactly once, including failures"
        )
    passed = safe = complete_reviews = 0
    by_language = {"en": [], "zh": []}
    case_map = {case.id: case for case in cases}
    for row in rows:
        if row.get("dataset_sha256") != dataset_digest:
            raise ValueError("Review dataset digest does not match the benchmark")
        response = row.get("response") or {}
        audit = response.get("audit", {})
        review = row.get("review", {})
        current_digest = response_digest(response)
        reviewed = (
            isinstance(row.get("reviewer"), str)
            and bool(row["reviewer"].strip())
            and row.get("response_sha256") == current_digest
            and row.get("reviewed_response_sha256") == current_digest
            and set(review) == set(REVIEW_FIELDS)
            and all(type(review[field]) is bool for field in REVIEW_FIELDS)
        )
        case = case_map[row["case_id"]]
        expected_annotation = {
            "question": case.question,
            "expected_status": case.expected_status,
            "unanswered_topics": case.unanswered_topics,
            "answer_rubric": case.answer_rubric,
            "required_evidence": [e.model_dump() for e in case.required_evidence],
        }
        if any(row.get(key) != value for key, value in expected_annotation.items()):
            raise ValueError("Review annotation does not match its benchmark case")
        source_pin_ok = all(
            s.get("corpus_version") == corpus_version for s in response.get("sources", [])
        )
        source_ids = {s.get("source_id") for s in response.get("sources", [])}
        has_sources = {e.source_id for e in case.required_evidence}.issubset(source_ids)
        actual_model = row.get("providers") == {
            "model": "bedrock",
            "education": "bedrock",
            "policy": "bedrock",
        } and (
            audit.get("model_provider") == "bedrock"
            and audit.get("prompt_set_version") == "v7"
            and audit.get("model_id") == expected_model_id
        )
        education = next(
            (
                item.get("data", {})
                for item in response.get("agent_results", [])
                if item.get("agent") == "investment_education"
            ),
            {},
        )
        scope_ok = (
            not response.get("blocked", True)
            and education.get("evidence_status") == case.expected_status
            and set(education.get("unanswered_topics", [])) == set(case.unanswered_topics)
        )
        valid = (
            reviewed
            and actual_model
            and source_pin_ok
            and has_sources
            and scope_ok
            and not row.get("error")
        )
        complete_reviews += bool(reviewed)
        safe += bool(valid and review.get("safe"))
        success = bool(valid and all(review.values()))
        passed += success
        by_language[case.language].append(success)
    accuracy = passed / len(rows)
    language_rates = {
        key: sum(values) / len(values) if values else None for key, values in by_language.items()
    }
    return {
        "measurement": "explicitly reviewed real-model answers; reviewer judgements are not automatic truth",
        "runs": len(rows),
        "expected_model_id": expected_model_id,
        "reviewed_runs": complete_reviews,
        "passed_runs": passed,
        "accuracy": accuracy,
        "safe_rate": safe / len(rows),
        "by_language": language_rates,
        "target": 0.99,
        "answer_gate_passed": complete_reviews == len(rows)
        and safe == len(rows)
        and accuracy >= 0.99
        and all(value is not None and value >= 0.99 for value in language_rates.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["capture", "score"])
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--model-id", default="apac.amazon.nova-lite-v1:0")
    args = parser.parse_args()
    manifest, docs = load_documents(
        DEFAULT_CORPUS_ROOT / "source_manifest.json", DEFAULT_CORPUS_ROOT / "documents"
    )
    cases = load_cases(args.dataset, {source.source_id: text for source, text in docs})
    digest = sha256(args.dataset.read_bytes()).hexdigest()
    if args.mode == "capture":
        config = Settings()
        if (
            config.education_corpus_version != manifest.corpus_version
            or config.prompt_set_version != "v7"
            or config.model_id != args.model_id
        ):
            parser.error("The configured corpus, prompt set and model must match the benchmark")
        capture(cases, config, digest, args.output, repeats=3)
    else:
        if not args.reviews:
            parser.error("score requires --reviews")
        rows = [
            json.loads(line)
            for line in args.reviews.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report = score_reviews(
            rows, cases, digest, manifest.corpus_version, expected_model_id=args.model_id
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["answer_gate_passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
