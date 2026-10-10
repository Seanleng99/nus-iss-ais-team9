import json
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.telemetry import log_event


class StrictGovernanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApprovedDocumentMetadata(StrictGovernanceModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    title: str = Field(min_length=1, max_length=300)
    issuing_organization: str = Field(min_length=1, max_length=200)
    canonical_url: str = Field(pattern=r"^https://")
    published_at: date
    ingested_at: datetime
    document_version: str = Field(min_length=1, max_length=64)
    checksum: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    review_status: Literal["approved"]
    corpus_version: str = Field(min_length=1, max_length=128)
    manifest_schema_version: Literal[2]
    review_due_at: date
    usage_scope: Literal["synthetic_demo_only"]
    document_filename: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.md$",
    )
    content_kind: Literal["source_document", "project_summary"] | None = None


class GovernedSource(StrictGovernanceModel):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    title: str = Field(min_length=1, max_length=300)
    issuing_organization: str = Field(min_length=1, max_length=200)
    canonical_url: str = Field(pattern=r"^https://")
    published_at: date
    document_version: str = Field(min_length=1, max_length=64)
    checksum: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    s3_document_key: str = Field(min_length=1, max_length=1024)
    s3_metadata_key: str = Field(min_length=1, max_length=1024)
    topics: list[str] = Field(min_length=1)
    source_review_status: Literal["approved", "pending", "withdrawn"]
    content_review_status: Literal["approved", "pending", "rejected"]
    rights_review_status: Literal[
        "public_reference_reviewed_for_demo",
        "internal_policy_approved_for_demo",
    ]
    usage_scope: Literal["synthetic_demo_only"]
    ingestion_approved: bool
    last_verified_at: date
    review_due_at: date
    withdrawn_at: date | None = None
    content_kind: Literal["source_document", "project_summary"] | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "GovernedSource":
        log_event("VV entering ", "app.rag.ingestion.GovernedSource", "validate_lifecycle")
        if self.s3_metadata_key != f"{self.s3_document_key}.metadata.json":
            raise ValueError("metadata key must be the document key plus .metadata.json")
        if self.review_due_at < self.last_verified_at:
            raise ValueError("review_due_at must not precede last_verified_at")
        if self.ingestion_approved:
            if self.source_review_status != "approved":
                raise ValueError("ingestion requires approved source review")
            if self.content_review_status != "approved":
                raise ValueError("ingestion requires approved content review")
            if self.withdrawn_at is not None:
                raise ValueError("withdrawn sources cannot remain approved for ingestion")
        if self.source_review_status == "withdrawn":
            if self.ingestion_approved or self.withdrawn_at is None:
                raise ValueError("withdrawn sources require a date and disabled ingestion")
        elif self.withdrawn_at is not None:
            raise ValueError("only withdrawn sources may have withdrawn_at")
        return self


class SourceManifest(StrictGovernanceModel):
    schema_version: Literal[2]
    collection_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")
    corpus_version: str = Field(pattern=r"^[a-z0-9][a-z0-9@._-]{2,127}$")
    scope: str = Field(min_length=1, max_length=500)
    jurisdiction: Literal["SG"]
    owner_role: str = Field(min_length=1, max_length=128)
    approval_reference: str = Field(min_length=1, max_length=256)
    approved_at: date
    manifest_status: Literal["approved_for_ingestion", "suspended", "withdrawn"]
    s3_prefix: str = Field(pattern=r"^[a-zA-Z0-9!_.*'()/-]+/$")
    sources: list[GovernedSource] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_collection(self) -> "SourceManifest":
        log_event("VV entering ", "app.rag.ingestion.SourceManifest", "validate_collection")
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source IDs must be unique")
        document_keys = [source.s3_document_key for source in self.sources]
        if len(document_keys) != len(set(document_keys)):
            raise ValueError("document keys must be unique")
        metadata_keys = [source.s3_metadata_key for source in self.sources]
        if len(metadata_keys) != len(set(metadata_keys)):
            raise ValueError("metadata keys must be unique")
        for source in self.sources:
            if not source.s3_document_key.startswith(self.s3_prefix):
                raise ValueError("document keys must remain inside the manifest prefix")
            if not source.s3_metadata_key.startswith(self.s3_prefix):
                raise ValueError("metadata keys must remain inside the manifest prefix")
        return self


def load_source_manifest(path: Path) -> SourceManifest:
    log_event("VV entering ", "app.rag.ingestion", "load_source_manifest")
    return SourceManifest.model_validate_json(path.read_text(encoding="utf-8"))


def active_sources(manifest: SourceManifest) -> list[GovernedSource]:
    log_event("VV entering ", "app.rag.ingestion", "active_sources")
    return [source for source in manifest.sources if source.ingestion_approved]


def governance_issues(
    manifest: SourceManifest,
    *,
    as_of: date | None = None,
) -> list[dict[str, str]]:
    log_event("VV entering ", "app.rag.ingestion", "governance_issues")
    checked_on = as_of or datetime.now(UTC).date()
    issues: list[dict[str, str]] = []
    if manifest.manifest_status != "approved_for_ingestion":
        issues.append(
            {
                "code": "MANIFEST_NOT_APPROVED",
                "subject": manifest.collection_id,
            }
        )
    for source in active_sources(manifest):
        if source.review_due_at < checked_on:
            issues.append(
                {
                    "code": "SOURCE_REVIEW_EXPIRED",
                    "subject": source.source_id,
                }
            )
        if source.last_verified_at > checked_on:
            issues.append(
                {
                    "code": "SOURCE_VERIFICATION_IN_FUTURE",
                    "subject": source.source_id,
                }
            )
    return issues


def manifest_digest(manifest: SourceManifest) -> str:
    log_event("VV entering ", "app.rag.ingestion", "manifest_digest")
    canonical = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(canonical).hexdigest()}"


def metadata_for_source(
    manifest: SourceManifest,
    source: GovernedSource,
    *,
    ingested_at: datetime,
) -> ApprovedDocumentMetadata:
    log_event("VV entering ", "app.rag.ingestion", "metadata_for_source")
    return ApprovedDocumentMetadata(
        source_id=source.source_id,
        title=source.title,
        issuing_organization=source.issuing_organization,
        canonical_url=source.canonical_url,
        published_at=source.published_at,
        ingested_at=ingested_at,
        document_version=source.document_version,
        checksum=source.checksum,
        review_status="approved",
        corpus_version=manifest.corpus_version,
        manifest_schema_version=manifest.schema_version,
        review_due_at=source.review_due_at,
        usage_scope=source.usage_scope,
        document_filename=Path(source.s3_document_key).name,
        content_kind=source.content_kind,
    )


def build_metadata_sidecar(document: ApprovedDocumentMetadata) -> dict:
    log_event("VV entering ", "app.rag.ingestion", "build_metadata_sidecar")
    return {"metadataAttributes": document.model_dump(mode="json", exclude_none=True)}
