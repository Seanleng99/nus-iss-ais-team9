from app.rag.ingestion import ApprovedDocumentMetadata, build_metadata_sidecar


def test_approved_document_builds_bedrock_metadata_sidecar() -> None:
    document = ApprovedDocumentMetadata(
        source_id="cpf-investment-scheme-guide",
        title="CPF Investment Scheme: what you need to know about CPFIS",
        issuing_organization="CPF Board",
        canonical_url=(
            "https://www.cpf.gov.sg/member/infohub/educational-resources/"
            "cpf-investment-scheme-what-you-need-to-know-about-cpfis"
        ),
        published_at="2026-02-09",
        ingested_at="2026-08-15T03:00:00Z",
        document_version="2026-02-09",
        checksum="sha256:approved-checksum",
        review_status="approved",
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
            "checksum": "sha256:approved-checksum",
            "review_status": "approved",
        }
    }
