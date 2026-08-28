import argparse
import json
import os
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_SERVICE_ROOT = REPO_ROOT / "apps" / "ai-service"
for import_root in (REPO_ROOT, AI_SERVICE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.core.guardrails import sanitize_rag_document
from app.rag.ingestion import (
    ApprovedDocumentMetadata,
    GovernedSource,
    SourceManifest,
    active_sources,
    build_metadata_sidecar,
    governance_issues,
    load_source_manifest,
    manifest_digest,
    metadata_for_source,
)


def _parse_date(value: str | None) -> date:
    return date.fromisoformat(value) if value else datetime.now(UTC).date()


def _checksum(content: bytes) -> str:
    return f"sha256:{sha256(content).hexdigest()}"


def _safe_error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
        if code and len(code) <= 64 and code.replace("_", "").isalnum():
            return code.upper()
    return type(exc).__name__.upper()


def _issue(code: str, subject: str) -> dict[str, str]:
    return {"code": code, "subject": subject}


def validate_manifest(
    manifest: SourceManifest,
    *,
    as_of: date,
) -> dict[str, Any]:
    issues = governance_issues(manifest, as_of=as_of)
    approved = active_sources(manifest)
    return {
        "collection_id": manifest.collection_id,
        "corpus_version": manifest.corpus_version,
        "manifest_schema_version": manifest.schema_version,
        "manifest_digest": manifest_digest(manifest),
        "jurisdiction": manifest.jurisdiction,
        "usage_scopes": sorted({source.usage_scope for source in manifest.sources}),
        "checked_on": as_of.isoformat(),
        "source_count": len(manifest.sources),
        "approved_source_count": len(approved),
        "withdrawn_source_count": sum(
            source.source_review_status == "withdrawn" for source in manifest.sources
        ),
        "earliest_review_due_at": min(
            (source.review_due_at for source in approved),
            default=None,
        ),
        "issues": issues,
        "passed": not issues,
    }


def _local_document_path(documents_dir: Path, source: GovernedSource) -> Path:
    return documents_dir / Path(source.s3_document_key).name


def prepare_documents(
    manifest: SourceManifest,
    *,
    documents_dir: Path,
    staging_dir: Path,
    as_of: date,
    ingested_at: datetime | None = None,
) -> dict[str, Any]:
    report = validate_manifest(manifest, as_of=as_of)
    issues = list(report["issues"])
    prepared = []
    timestamp = ingested_at or datetime.now(UTC)
    staging_dir.mkdir(parents=True, exist_ok=True)

    for source in active_sources(manifest):
        document_path = _local_document_path(documents_dir, source)
        if not document_path.is_file():
            issues.append(_issue("LOCAL_DOCUMENT_MISSING", source.source_id))
            continue
        content = document_path.read_bytes()
        actual_checksum = _checksum(content)
        if actual_checksum != source.checksum:
            issues.append(_issue("DOCUMENT_CHECKSUM_MISMATCH", source.source_id))
            continue
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(_issue("DOCUMENT_NOT_UTF8", source.source_id))
            continue
        inspection = sanitize_rag_document(text)
        if inspection.findings:
            issues.append(_issue("DOCUMENT_GUARDRAIL_FINDING", source.source_id))
            continue

        staged_document = staging_dir / Path(source.s3_document_key).name
        staged_metadata = staging_dir / Path(source.s3_metadata_key).name
        staged_document.write_bytes(content)
        metadata = metadata_for_source(
            manifest,
            source,
            ingested_at=timestamp,
        )
        staged_metadata.write_text(
            json.dumps(build_metadata_sidecar(metadata), indent=2) + "\n",
            encoding="utf-8",
        )
        prepared.append(
            {
                "source_id": source.source_id,
                "document_key": source.s3_document_key,
                "metadata_key": source.s3_metadata_key,
                "checksum": actual_checksum,
            }
        )

    report.update(
        {
            "prepared_source_count": len(prepared),
            "prepared_sources": prepared,
            "issues": issues,
            "passed": not issues and len(prepared) == len(active_sources(manifest)),
        }
    )
    return report


def _read_s3_body(response: dict[str, Any]) -> bytes:
    body = response["Body"]
    content = body.read() if hasattr(body, "read") else body
    return content if isinstance(content, bytes) else bytes(content)


def _list_s3_keys(client: Any, *, bucket: str, prefix: str) -> set[str]:
    keys: set[str] = set()
    token = None
    while True:
        request: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if token:
            request["ContinuationToken"] = token
        response = client.list_objects_v2(**request)
        keys.update(
            str(item["Key"])
            for item in response.get("Contents", [])
            if item.get("Key")
        )
        if not response.get("IsTruncated"):
            return keys
        token = response.get("NextContinuationToken")
        if not token:
            raise RuntimeError("S3 pagination did not return a continuation token")


def _require_governed_aws_target(
    bedrock_client: Any,
    *,
    knowledge_base_id: str,
    data_source_id: str,
    bucket: str,
    prefix: str,
) -> None:
    knowledge_base = bedrock_client.get_knowledge_base(
        knowledgeBaseId=knowledge_base_id
    )["knowledgeBase"]
    data_source = bedrock_client.get_data_source(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
    )["dataSource"]
    if knowledge_base.get("status") != "ACTIVE":
        raise ValueError("the target knowledge base is not active")
    if data_source.get("status") != "AVAILABLE":
        raise ValueError("the target data source is not available")
    s3_configuration = data_source.get("dataSourceConfiguration", {}).get(
        "s3Configuration", {}
    )
    if s3_configuration.get("bucketArn") != f"arn:aws:s3:::{bucket}":
        raise ValueError("the target bucket does not match the Bedrock data source")
    if s3_configuration.get("inclusionPrefixes") != [prefix]:
        raise ValueError("the target prefix does not exactly match the Bedrock data source")


def _metadata_mismatches(
    manifest: SourceManifest,
    source: GovernedSource,
    metadata: ApprovedDocumentMetadata,
) -> list[str]:
    expected = {
        "source_id": source.source_id,
        "title": source.title,
        "issuing_organization": source.issuing_organization,
        "canonical_url": source.canonical_url,
        "published_at": source.published_at,
        "document_version": source.document_version,
        "checksum": source.checksum,
        "review_status": "approved",
        "corpus_version": manifest.corpus_version,
        "manifest_schema_version": manifest.schema_version,
        "review_due_at": source.review_due_at,
        "usage_scope": source.usage_scope,
    }
    return [
        key
        for key, value in expected.items()
        if getattr(metadata, key) != value
    ]


def audit_aws_corpus(
    manifest: SourceManifest,
    *,
    knowledge_base_id: str,
    data_source_id: str,
    bucket: str,
    prefix: str,
    region: str,
    as_of: date,
    bedrock_client: Any | None = None,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    if prefix != manifest.s3_prefix:
        raise ValueError("configured S3 prefix does not match the approved manifest")
    if bedrock_client is None or s3_client is None:
        import boto3

        bedrock_client = bedrock_client or boto3.client("bedrock-agent", region_name=region)
        s3_client = s3_client or boto3.client("s3", region_name=region)

    base = validate_manifest(manifest, as_of=as_of)
    issues = list(base["issues"])
    knowledge_base = bedrock_client.get_knowledge_base(
        knowledgeBaseId=knowledge_base_id
    )["knowledgeBase"]
    data_source = bedrock_client.get_data_source(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
    )["dataSource"]
    if knowledge_base.get("status") != "ACTIVE":
        issues.append(_issue("KNOWLEDGE_BASE_NOT_ACTIVE", knowledge_base_id))
    if data_source.get("status") != "AVAILABLE":
        issues.append(_issue("DATA_SOURCE_NOT_AVAILABLE", data_source_id))

    s3_configuration = data_source.get("dataSourceConfiguration", {}).get(
        "s3Configuration", {}
    )
    if s3_configuration.get("bucketArn") != f"arn:aws:s3:::{bucket}":
        issues.append(_issue("DATA_SOURCE_BUCKET_MISMATCH", data_source_id))
    if prefix not in s3_configuration.get("inclusionPrefixes", []):
        issues.append(_issue("DATA_SOURCE_PREFIX_MISMATCH", data_source_id))

    jobs = bedrock_client.list_ingestion_jobs(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        maxResults=10,
        sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"},
    ).get("ingestionJobSummaries", [])
    latest_job = jobs[0] if jobs else None
    if latest_job is None:
        issues.append(_issue("INGESTION_JOB_MISSING", data_source_id))
    elif latest_job.get("status") != "COMPLETE":
        issues.append(_issue("LATEST_INGESTION_NOT_COMPLETE", data_source_id))
    elif int(latest_job.get("statistics", {}).get("numberOfDocumentsFailed", 0)):
        issues.append(_issue("LATEST_INGESTION_HAS_FAILURES", data_source_id))

    deployed_keys = _list_s3_keys(s3_client, bucket=bucket, prefix=prefix)
    governed_keys = {
        key
        for source in manifest.sources
        for key in (source.s3_document_key, source.s3_metadata_key)
    }
    for key in sorted(deployed_keys - governed_keys):
        issues.append(_issue("UNMANIFESTED_S3_OBJECT", key))

    source_evidence = []
    for source in manifest.sources:
        expected_present = source.ingestion_approved
        source_keys = {source.s3_document_key, source.s3_metadata_key}
        if not expected_present:
            for key in sorted(source_keys.intersection(deployed_keys)):
                issues.append(_issue("WITHDRAWN_SOURCE_STILL_DEPLOYED", key))
            source_evidence.append(
                {
                    "source_id": source.source_id,
                    "expected_state": "withdrawn",
                    "deployed": bool(source_keys.intersection(deployed_keys)),
                }
            )
            continue
        missing_keys = source_keys - deployed_keys
        for key in sorted(missing_keys):
            issues.append(_issue("APPROVED_S3_OBJECT_MISSING", key))
        if missing_keys:
            continue

        document = _read_s3_body(
            s3_client.get_object(Bucket=bucket, Key=source.s3_document_key)
        )
        actual_checksum = _checksum(document)
        if actual_checksum != source.checksum:
            issues.append(_issue("DEPLOYED_CHECKSUM_MISMATCH", source.source_id))
        try:
            sidecar = json.loads(
                _read_s3_body(
                    s3_client.get_object(Bucket=bucket, Key=source.s3_metadata_key)
                ).decode("utf-8")
            )
            metadata = ApprovedDocumentMetadata.model_validate(
                sidecar["metadataAttributes"]
            )
            mismatches = _metadata_mismatches(manifest, source, metadata)
            for field in mismatches:
                issues.append(
                    _issue("DEPLOYED_METADATA_MISMATCH", f"{source.source_id}:{field}")
                )
        except (KeyError, TypeError, UnicodeDecodeError, ValueError) as exc:
            issues.append(
                _issue("DEPLOYED_METADATA_INVALID", f"{source.source_id}:{_safe_error_code(exc)}")
            )
            mismatches = ["invalid"]

        source_evidence.append(
            {
                "source_id": source.source_id,
                "expected_state": "approved",
                "deployed": True,
                "checksum": actual_checksum,
                "checksum_matches": actual_checksum == source.checksum,
                "metadata_matches": not mismatches,
                "review_due_at": source.review_due_at.isoformat(),
            }
        )

    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": "audit_aws",
        **base,
        "aws": {
            "region": region,
            "knowledge_base_id": knowledge_base_id,
            "knowledge_base_status": knowledge_base.get("status"),
            "embedding_model_arn": knowledge_base.get(
                "knowledgeBaseConfiguration", {}
            )
            .get("vectorKnowledgeBaseConfiguration", {})
            .get("embeddingModelArn"),
            "data_source_id": data_source_id,
            "data_source_status": data_source.get("status"),
            "bucket": bucket,
            "prefix": prefix,
            "object_count": len(deployed_keys),
            "latest_ingestion_job": {
                key: latest_job.get(key)
                for key in ("ingestionJobId", "status", "startedAt", "updatedAt", "statistics")
            }
            if latest_job
            else None,
        },
        "source_evidence": source_evidence,
        "issues": issues,
        "passed": not issues,
    }
    return report


def _wait_for_ingestion(
    client: Any,
    *,
    knowledge_base_id: str,
    data_source_id: str,
    ingestion_job_id: str,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = client.get_ingestion_job(
            knowledgeBaseId=knowledge_base_id,
            dataSourceId=data_source_id,
            ingestionJobId=ingestion_job_id,
        )["ingestionJob"]
        if job.get("status") in {"COMPLETE", "FAILED", "STOPPED"}:
            return job
        if time.monotonic() >= deadline:
            raise TimeoutError("Bedrock ingestion did not finish within the approved timeout")
        time.sleep(10)


def apply_corpus(
    manifest: SourceManifest,
    *,
    documents_dir: Path,
    bucket: str,
    knowledge_base_id: str,
    data_source_id: str,
    region: str,
    confirmation: str,
    as_of: date,
    bedrock_client: Any | None = None,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    if confirmation != manifest.corpus_version:
        raise ValueError("--confirm-corpus-version must exactly match the manifest")
    if bedrock_client is None or s3_client is None:
        import boto3

        bedrock_client = bedrock_client or boto3.client("bedrock-agent", region_name=region)
        s3_client = s3_client or boto3.client("s3", region_name=region)
    _require_governed_aws_target(
        bedrock_client,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
        bucket=bucket,
        prefix=manifest.s3_prefix,
    )

    with tempfile.TemporaryDirectory(prefix="rag-governance-") as temporary:
        staged = Path(temporary)
        preparation = prepare_documents(
            manifest,
            documents_dir=documents_dir,
            staging_dir=staged,
            as_of=as_of,
        )
        if not preparation["passed"]:
            return {"operation": "apply", **preparation}
        for source in active_sources(manifest):
            document = (staged / Path(source.s3_document_key).name).read_bytes()
            sidecar = (staged / Path(source.s3_metadata_key).name).read_bytes()
            s3_client.put_object(
                Bucket=bucket,
                Key=source.s3_document_key,
                Body=document,
                ContentType="text/markdown; charset=utf-8",
                ServerSideEncryption="AES256",
            )
            s3_client.put_object(
                Bucket=bucket,
                Key=source.s3_metadata_key,
                Body=sidecar,
                ContentType="application/json",
                ServerSideEncryption="AES256",
            )

    started = bedrock_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        clientToken=str(uuid4()),
        description=f"Governed corpus {manifest.corpus_version}",
    )["ingestionJob"]
    completed = _wait_for_ingestion(
        bedrock_client,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
        ingestion_job_id=started["ingestionJobId"],
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": "apply",
        **preparation,
        "knowledge_base_id": knowledge_base_id,
        "data_source_id": data_source_id,
        "ingestion_job_id": completed.get("ingestionJobId"),
        "ingestion_status": completed.get("status"),
        "ingestion_statistics": completed.get("statistics", {}),
        "passed": completed.get("status") == "COMPLETE"
        and not completed.get("failureReasons"),
    }


def publish_metadata(
    manifest: SourceManifest,
    *,
    bucket: str,
    knowledge_base_id: str,
    data_source_id: str,
    region: str,
    confirmation: str,
    as_of: date,
    bedrock_client: Any | None = None,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    if confirmation != manifest.corpus_version:
        raise ValueError("--confirm-corpus-version must exactly match the manifest")
    if bedrock_client is None or s3_client is None:
        import boto3

        bedrock_client = bedrock_client or boto3.client("bedrock-agent", region_name=region)
        s3_client = s3_client or boto3.client("s3", region_name=region)
    _require_governed_aws_target(
        bedrock_client,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
        bucket=bucket,
        prefix=manifest.s3_prefix,
    )

    base = validate_manifest(manifest, as_of=as_of)
    issues = list(base["issues"])
    documents: dict[str, bytes] = {}
    for source in active_sources(manifest):
        try:
            content = _read_s3_body(
                s3_client.get_object(Bucket=bucket, Key=source.s3_document_key)
            )
        except Exception as exc:  # noqa: BLE001 -- provider failures become sanitized evidence
            issues.append(
                _issue("APPROVED_S3_OBJECT_UNREADABLE", f"{source.source_id}:{_safe_error_code(exc)}")
            )
            continue
        if _checksum(content) != source.checksum:
            issues.append(_issue("DEPLOYED_CHECKSUM_MISMATCH", source.source_id))
            continue
        try:
            inspection = sanitize_rag_document(content.decode("utf-8"))
        except UnicodeDecodeError:
            issues.append(_issue("DOCUMENT_NOT_UTF8", source.source_id))
            continue
        if inspection.findings:
            issues.append(_issue("DOCUMENT_GUARDRAIL_FINDING", source.source_id))
            continue
        documents[source.source_id] = content

    if issues or len(documents) != len(active_sources(manifest)):
        return {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "operation": "publish_metadata",
            **base,
            "issues": issues,
            "passed": False,
        }

    timestamp = datetime.now(UTC)
    for source in active_sources(manifest):
        metadata = metadata_for_source(manifest, source, ingested_at=timestamp)
        s3_client.put_object(
            Bucket=bucket,
            Key=source.s3_metadata_key,
            Body=(json.dumps(build_metadata_sidecar(metadata), indent=2) + "\n").encode(),
            ContentType="application/json",
            ServerSideEncryption="AES256",
        )
    started = bedrock_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        clientToken=str(uuid4()),
        description=f"Governed metadata {manifest.corpus_version}",
    )["ingestionJob"]
    completed = _wait_for_ingestion(
        bedrock_client,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
        ingestion_job_id=started["ingestionJobId"],
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": "publish_metadata",
        **base,
        "updated_metadata_count": len(documents),
        "ingestion_job_id": completed.get("ingestionJobId"),
        "ingestion_status": completed.get("status"),
        "ingestion_statistics": completed.get("statistics", {}),
        "issues": issues,
        "passed": completed.get("status") == "COMPLETE"
        and not completed.get("failureReasons"),
    }


def withdraw_source(
    manifest: SourceManifest,
    *,
    source_id: str,
    confirmation: str,
    bucket: str,
    knowledge_base_id: str,
    data_source_id: str,
    region: str,
    bedrock_client: Any | None = None,
    s3_client: Any | None = None,
) -> dict[str, Any]:
    source = next((item for item in manifest.sources if item.source_id == source_id), None)
    if source is None:
        raise ValueError("source ID does not exist in the manifest")
    if confirmation != source_id:
        raise ValueError("--confirm-source-id must exactly match the withdrawn source")
    if source.source_review_status != "withdrawn" or source.ingestion_approved:
        raise ValueError("the reviewed manifest must withdraw the source before deletion")
    if bedrock_client is None or s3_client is None:
        import boto3

        bedrock_client = bedrock_client or boto3.client("bedrock-agent", region_name=region)
        s3_client = s3_client or boto3.client("s3", region_name=region)
    _require_governed_aws_target(
        bedrock_client,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
        bucket=bucket,
        prefix=manifest.s3_prefix,
    )
    deleted_keys = [source.s3_document_key, source.s3_metadata_key]
    for key in deleted_keys:
        s3_client.delete_object(Bucket=bucket, Key=key)
    started = bedrock_client.start_ingestion_job(
        knowledgeBaseId=knowledge_base_id,
        dataSourceId=data_source_id,
        clientToken=str(uuid4()),
        description=f"Withdraw governed source {source_id}",
    )["ingestionJob"]
    completed = _wait_for_ingestion(
        bedrock_client,
        knowledge_base_id=knowledge_base_id,
        data_source_id=data_source_id,
        ingestion_job_id=started["ingestionJobId"],
    )
    base = validate_manifest(manifest, as_of=datetime.now(UTC).date())
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "operation": "withdraw",
        **base,
        "source_id": source_id,
        "deleted_keys": deleted_keys,
        "ingestion_job_id": completed.get("ingestionJobId"),
        "ingestion_status": completed.get("status"),
        "ingestion_statistics": completed.get("statistics", {}),
        "passed": completed.get("status") == "COMPLETE"
        and not completed.get("failureReasons"),
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")


def _write_job_summary(report: dict[str, Any]) -> None:
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## Education RAG source governance",
        "",
        f"- Operation: `{report.get('operation', 'validate')}`",
        f"- Corpus version: `{report['corpus_version']}`",
        f"- Approved sources: {report['approved_source_count']}",
        f"- Result: **{'PASS' if report['passed'] else 'FAIL'}**",
    ]
    if report.get("issues"):
        lines.extend(
            ["", "### Issues", ""]
            + [
                f"- `{issue['code']}`: `{issue['subject']}`"
                for issue in report["issues"]
            ]
        )
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def _add_aws_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--data-source-id", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-southeast-1"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Govern the approved Education RAG corpus")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in (
        "validate",
        "prepare",
        "audit-aws",
        "apply",
        "publish-metadata",
        "withdraw",
    ):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--manifest", required=True, type=Path)
        subparser.add_argument("--output", required=True, type=Path)
        subparser.add_argument("--as-of")
        if name in {"audit-aws", "apply", "publish-metadata", "withdraw"}:
            _add_aws_arguments(subparser)
        if name in {"prepare", "apply"}:
            subparser.add_argument("--documents-dir", required=True, type=Path)
        if name == "prepare":
            subparser.add_argument("--staging-dir", required=True, type=Path)
        if name in {"apply", "publish-metadata"}:
            subparser.add_argument("--confirm-corpus-version", required=True)
        if name == "withdraw":
            subparser.add_argument("--source-id", required=True)
            subparser.add_argument("--confirm-source-id", required=True)
    args = parser.parse_args()

    manifest = load_source_manifest(args.manifest)
    checked_on = _parse_date(args.as_of)
    try:
        if args.operation == "validate":
            report = {
                "schema_version": 1,
                "generated_at": datetime.now(UTC).isoformat(),
                "operation": "validate",
                **validate_manifest(manifest, as_of=checked_on),
            }
        elif args.operation == "prepare":
            report = {
                "schema_version": 1,
                "generated_at": datetime.now(UTC).isoformat(),
                "operation": "prepare",
                **prepare_documents(
                    manifest,
                    documents_dir=args.documents_dir,
                    staging_dir=args.staging_dir,
                    as_of=checked_on,
                ),
            }
        elif args.operation == "audit-aws":
            report = audit_aws_corpus(
                manifest,
                knowledge_base_id=args.knowledge_base_id,
                data_source_id=args.data_source_id,
                bucket=args.bucket,
                prefix=args.prefix,
                region=args.region,
                as_of=checked_on,
            )
        elif args.operation == "apply":
            report = apply_corpus(
                manifest,
                documents_dir=args.documents_dir,
                bucket=args.bucket,
                knowledge_base_id=args.knowledge_base_id,
                data_source_id=args.data_source_id,
                region=args.region,
                confirmation=args.confirm_corpus_version,
                as_of=checked_on,
            )
        elif args.operation == "publish-metadata":
            report = publish_metadata(
                manifest,
                bucket=args.bucket,
                knowledge_base_id=args.knowledge_base_id,
                data_source_id=args.data_source_id,
                region=args.region,
                confirmation=args.confirm_corpus_version,
                as_of=checked_on,
            )
        else:
            report = withdraw_source(
                manifest,
                source_id=args.source_id,
                confirmation=args.confirm_source_id,
                bucket=args.bucket,
                knowledge_base_id=args.knowledge_base_id,
                data_source_id=args.data_source_id,
                region=args.region,
            )
    except Exception as exc:  # noqa: BLE001 -- always emit a sanitized governance artifact
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "operation": args.operation,
            **validate_manifest(manifest, as_of=checked_on),
            "issues": [_issue("GOVERNANCE_EXECUTION_FAILED", _safe_error_code(exc))],
            "passed": False,
        }

    _write_report(args.output, report)
    _write_job_summary(report)
    print(
        json.dumps(
            {
                "operation": report["operation"],
                "corpus_version": report["corpus_version"],
                "approved_source_count": report["approved_source_count"],
                "issue_count": len(report.get("issues", [])),
                "passed": report["passed"],
            },
            indent=2,
        )
    )
    if not report["passed"]:
        raise SystemExit("Education RAG source governance failed")


if __name__ == "__main__":
    main()
