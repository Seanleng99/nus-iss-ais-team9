from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.rag.ingestion import (
    ApprovedDocumentMetadata,
    GovernedSource,
    build_metadata_sidecar,
    governance_issues,
    load_source_manifest,
    manifest_digest,
)

MANIFEST_PATH = (
    Path(__file__).parents[3]
    / "knowledge"
    / "investment_education"
    / "source_manifest.json"
)
POLICY_MANIFEST_PATH = (
    Path(__file__).parents[3]
    / "knowledge"
    / "policy_controls"
    / "source_manifest.json"
)


def test_approved_document_builds_bedrock_metadata_sidecar() -> None:
    document = ApprovedDocumentMetadata(
        source_id="cpf-investment-scheme-guide",
        title="CPF Investment Scheme: what you need to know about CPFIS",
        issuing_organization="CPF Board",
        canonical_url=(
            "https://www.cpf.gov.sg/member/infohub/educational-resources/"
            "cpf-investment-scheme-what-you-need-to-know-about-cpfis"
        ),
        published_at=date(2026, 2, 9),
        ingested_at=datetime.fromisoformat("2026-08-15T03:00:00+00:00"),
        document_version="2026-02-09",
        checksum="sha256:" + "a" * 64,
        review_status="approved",
        corpus_version="investment-education-sg@2026-08-28.1",
        manifest_schema_version=2,
        review_due_at=date(2026, 11, 14),
        usage_scope="synthetic_demo_only",
    )

    sidecar = build_metadata_sidecar(document)

    assert sidecar == {
        "metadataAttributes": {
            "source_id": "cpf-investment-scheme-guide",
            "title": "CPF Investment Scheme: what you need to know about CPFIS",
            "issuing_organization": "CPF Board",
            "canonical_url": document.canonical_url,
            "published_at": "2026-02-09",
            "ingested_at": "2026-08-15T03:00:00Z",
            "document_version": "2026-02-09",
            "checksum": "sha256:" + "a" * 64,
            "review_status": "approved",
            "corpus_version": "investment-education-sg@2026-08-28.1",
            "manifest_schema_version": 2,
            "review_due_at": "2026-11-14",
            "usage_scope": "synthetic_demo_only",
        }
    }


def test_repository_manifest_is_current_and_has_stable_digest() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)

    assert manifest.schema_version == 2
    assert manifest.corpus_version == "investment-education-sg@2026-09-27.1"
    assert len(manifest.sources) == 10
    assert governance_issues(manifest, as_of=date(2026, 9, 26)) == []
    assert manifest_digest(manifest).startswith("sha256:")
    assert len(manifest_digest(manifest)) == 71


def test_policy_manifest_is_current_and_approved() -> None:
    manifest = load_source_manifest(POLICY_MANIFEST_PATH)

    assert manifest.collection_id == "financial-coach-policy-sg"
    assert manifest.corpus_version == "financial-coach-policy-sg@2026-08-29.1"
    assert len(manifest.sources) == 3
    assert {
        source.rights_review_status for source in manifest.sources
    } == {"internal_policy_approved_for_demo"}
    assert governance_issues(manifest, as_of=date(2026, 8, 29)) == []
    assert len(manifest_digest(manifest)) == 71


def test_manifest_reports_an_expired_source_review() -> None:
    manifest = load_source_manifest(MANIFEST_PATH)

    issues = governance_issues(manifest, as_of=date(2026, 11, 15))

    assert {item["code"] for item in issues} == {"SOURCE_REVIEW_EXPIRED"}
    assert len(issues) == 10


def test_withdrawn_source_cannot_remain_approved_for_ingestion() -> None:
    source = load_source_manifest(MANIFEST_PATH).sources[0]
    payload = source.model_dump(mode="json")
    payload.update(source_review_status="withdrawn", withdrawn_at="2026-08-28")

    with pytest.raises(ValidationError, match="approved source review"):
        GovernedSource.model_validate(payload)
