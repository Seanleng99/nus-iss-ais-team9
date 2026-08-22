from typing import Literal

from pydantic import BaseModel, Field


class ApprovedDocumentMetadata(BaseModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    issuing_organization: str = Field(min_length=1)
    canonical_url: str = Field(pattern=r"^https://")
    published_at: str = Field(min_length=1)
    ingested_at: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    checksum: str = Field(pattern=r"^sha256:")
    review_status: Literal["approved"]


def build_metadata_sidecar(document: ApprovedDocumentMetadata) -> dict:
    return {"metadataAttributes": document.model_dump()}
