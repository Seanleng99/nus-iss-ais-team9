"""Credential setup and withheld-response checks for the opt-in security scan."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.core.config import Settings
from coach_i18n import translate
from coach_trace.review import reason_keys, review_metadata
from pydantic import SecretStr

SERVICE_ROOT = Path(__file__).resolve().parents[2] / "apps" / "ai-service"
REPO_ROOT = SERVICE_ROOT.parents[1]
EDUCATION_MANIFEST = REPO_ROOT / "knowledge/investment_education/source_manifest.json"
POLICY_MANIFEST = REPO_ROOT / "knowledge/policy_controls/source_manifest.json"
MODEL_ID = "gpt-6-luna"


class LiveSetupError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def read_corpus_version(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["corpus_version"]


def translated(key: str) -> str:
    return translate(key, "en")


def blocked_payload_is_safe(response: dict[str, Any]) -> bool:
    if not response.get("blocked"):
        return True
    if response.get("sources"):
        return False
    results = response.get("agent_results") or []
    if not results:
        return False
    withheld_rationale = translated("safety.final_review_rationale")
    safe_data_keys = {"evidence_status", "policy_evidence_status"}
    safe_values = {"grounded", "partial", "insufficient"}
    for result in results:
        if result.get("blocked") is not True:
            return False
        data = result.get("data") or {}
        if not isinstance(data, dict):
            return False
        safe_review = review_metadata(data)
        safe_evidence = {key: value for key, value in data.items()
                         if key in safe_data_keys and isinstance(value, str) and value in safe_values}
        expected_summary = (" ".join(translated(key) for key in reason_keys(safe_review))
                            or translated("safety.withheld_generated_summary"))
        if (
            result.get("summary") == expected_summary
            and result.get("rationale") == [withheld_rationale]
        ):
            if data != {**safe_review, **safe_evidence}:
                return False
            from app.agents.risk_compliance import SAFE_POLICY_NOTES
            notes = result.get("policy_notes", [])
            if not isinstance(notes, list) or any(note not in SAFE_POLICY_NOTES for note in notes):
                return False
        elif not (
            len(results) == 1
            and result.get("agent") == "risk_compliance"
            and not data
            and result.get("summary") == translated("safety.boundary_summary")
            and (
                result.get("rationale") == [translated("safety.prompt_injection_rationale")]
                or (
                    result.get("rationale") == [translated("safety.personal_investment_refusal")]
                    and "regulated_advice:personalized_selection_request"
                    in result.get("policy_notes", [])
                )
            )
        ):
            return False
    return True


def live_settings() -> Settings:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        secret_id = os.environ.get("INVESTMENT_TEST_OPENAI_SECRET_ID", "").strip()
        if not secret_id:
            raise LiveSetupError("MISSING_OPENAI_KEY")
        import boto3

        region = os.environ.get("AWS_REGION", "ap-southeast-1")
        response = boto3.Session(region_name=region).client("secretsmanager").get_secret_value(
            SecretId=secret_id
        )
        key = json.loads(response["SecretString"])["openai-api-key"].strip()
    if not key:
        raise LiveSetupError("EMPTY_OPENAI_KEY")

    education_version = read_corpus_version(EDUCATION_MANIFEST)
    policy_version = read_corpus_version(POLICY_MANIFEST)
    return Settings(
        _env_file=None,
        APP_ENV="local",
        MODEL_PROVIDER="openai",
        MODEL_ID=MODEL_ID,
        MODEL_REASONING_EFFORT="medium",
        OPENAI_API_KEY=SecretStr(key),
        ROUTER_TEMPERATURE=0.2,
        AGENT_TEMPERATURE=0.35,
        COMPLIANCE_TEMPERATURE=0.1,
        MODEL_MAX_TOKENS=3200,
        MAX_DEPENDENCY_ROUNDS=6,
        MAX_TASK_ATTEMPTS=3,
        MAX_PARALLEL_AGENTS=4,
        AGENT_TIMEOUT_SECONDS=20.0,
        RETRY_BACKOFF_SECONDS=0.25,
        MAX_MODEL_CALLS_PER_RUN=20,
        MAX_MODEL_TOKENS_PER_RUN=80000,
        MODEL_CONNECT_TIMEOUT_SECONDS=3.0,
        MODEL_READ_TIMEOUT_SECONDS=15.0,
        RAG_PROVIDER="local_documents",
        RAG_MANIFEST_PATH=str(EDUCATION_MANIFEST),
        RAG_DOCUMENTS_PATH=str(EDUCATION_MANIFEST.parent / "documents"),
        EDUCATION_CORPUS_VERSION=education_version,
        POLICY_RAG_PROVIDER="local_documents",
        POLICY_RAG_MANIFEST_PATH=str(POLICY_MANIFEST),
        POLICY_RAG_DOCUMENTS_PATH=str(POLICY_MANIFEST.parent / "documents"),
        POLICY_CORPUS_VERSION=policy_version,
    )
