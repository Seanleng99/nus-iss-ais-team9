"""Validate the exact governed corpora bundled with the AI service image."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "ai-service"))

from app.rag.local_documents import LocalDocumentEducationRetriever
from app.rag.local_policy import LocalDocumentPolicyRetriever


def main() -> None:
    education = LocalDocumentEducationRetriever()
    policy = LocalDocumentPolicyRetriever()
    report = {
        "education_corpus_version": education.expected_corpus_version,
        "education_source_count": len(education.manifest.sources),
        "policy_corpus_version": policy.expected_corpus_version,
        "policy_source_count": len(policy.documents),
        "passed": True,
    }
    output = ROOT / "artifacts" / "packaged-corpus-governance.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
