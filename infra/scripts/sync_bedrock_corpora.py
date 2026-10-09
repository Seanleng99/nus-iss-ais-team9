"""Ingest or audit both approved KB corpora before publishing their runtime pins."""

import argparse
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from rag_source_governance import (
    apply_corpus,
    audit_aws_corpus,
    load_source_manifest,
    prepare_documents,
)

ROOT = Path(__file__).resolve().parents[2]


def resolve_target(client, knowledge_base_id, manifest):
    candidates = []
    paginator = client.get_paginator("list_data_sources")
    for page in paginator.paginate(knowledgeBaseId=knowledge_base_id):
        for summary in page.get("dataSourceSummaries", []):
            source = client.get_data_source(
                knowledgeBaseId=knowledge_base_id, dataSourceId=summary["dataSourceId"],
            )["dataSource"]
            config = source.get("dataSourceConfiguration", {}).get("s3Configuration", {})
            if source.get("status") == "AVAILABLE" and config.get("inclusionPrefixes") == [manifest.s3_prefix]:
                candidates.append((summary["dataSourceId"], config["bucketArn"].removeprefix("arn:aws:s3:::")))
    if len(candidates) != 1:
        raise ValueError(f"{manifest.collection_id} requires exactly one approved S3 data source")
    return candidates[0]


def sync_corpora(education_kb, policy_kb, region, output_dir, *, audit_only=False):
    import boto3

    client = boto3.client("bedrock-agent", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    today = datetime.now(UTC).date()
    corpora = []
    # Check both local manifests/documents before mutating either remote corpus.
    for name, directory, kb in (
        ("education", "investment_education", education_kb),
        ("policy", "policy_controls", policy_kb),
    ):
        root = ROOT / "knowledge" / directory
        manifest = load_source_manifest(root / "source_manifest.json")
        with tempfile.TemporaryDirectory(prefix="kb-preflight-") as temp:
            prepared = prepare_documents(
                manifest, documents_dir=root / "documents", staging_dir=Path(temp), as_of=today,
            )
        if not prepared["passed"]:
            raise ValueError(f"{name} corpus failed local governance")
        data_source, bucket = resolve_target(client, kb, manifest)
        corpora.append((name, root, manifest, kb, data_source, bucket))
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, root, manifest, kb, data_source, bucket in corpora:
        arguments = {
            "knowledge_base_id": kb, "data_source_id": data_source, "bucket": bucket,
            "region": region, "as_of": today, "bedrock_client": client, "s3_client": s3,
        }
        if not audit_only:
            report = apply_corpus(
                manifest, documents_dir=root / "documents",
                confirmation=manifest.corpus_version, **arguments,
            )
            (output_dir / f"{name}-ingestion.json").write_text(
                json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8",
            )
            if not report["passed"]:
                raise ValueError(f"{name} KB ingestion failed")
        report = audit_aws_corpus(manifest, prefix=manifest.s3_prefix, **arguments)
        (output_dir / f"{name}-audit.json").write_text(
            json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8",
        )
        if not report["passed"]:
            raise ValueError(f"{name} KB failed remote governance")
        print(json.dumps({"corpus": name, "version": manifest.corpus_version, "passed": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--education-kb", required=True)
    parser.add_argument("--policy-kb", required=True)
    parser.add_argument("--region", default="ap-southeast-1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "artifacts" / "bedrock-governance")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    sync_corpora(args.education_kb, args.policy_kb, args.region, args.output_dir, audit_only=args.audit_only)


if __name__ == "__main__":
    main()
