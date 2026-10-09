"""Deployment boundaries and preflight for the restored retrieval pipeline."""

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "infra/scripts"))
SPEC = importlib.util.spec_from_file_location("sync_bedrock_corpora", ROOT / "infra/scripts/sync_bedrock_corpora.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def template(name):
    return yaml.load((ROOT / "infra/aws" / name).read_text(), Loader=yaml.BaseLoader)


def test_runtime_can_only_retrieve_from_the_two_configured_knowledge_bases():
    policy = template("demo-knowledge-bases.yaml")["Resources"]["AiTaskRetrievalPolicy"]["Properties"]
    statements = policy["PolicyDocument"]["Statement"]
    assert len(statements) == 1
    assert statements[0]["Action"] == "bedrock:Retrieve"
    assert len(statements[0]["Resource"]) == 2
    assert all("knowledge-base/" in str(resource) for resource in statements[0]["Resource"])


def test_read_only_governance_has_no_ingestion_or_model_generation_permission():
    resources = template("github-actions-oidc.yaml")["Resources"]
    assert "Policies" not in resources["RagGovernanceRole"]["Properties"]
    statements = resources["GovernedCorpusReadPolicy"]["Properties"]["PolicyDocument"]["Statement"]
    actions = {action for statement in statements for action in (
        statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
    )}
    assert actions >= {"bedrock:Retrieve", "s3:GetObject", "s3:ListBucket"}
    assert not actions & {"s3:PutObject", "s3:DeleteObject", "bedrock:StartIngestionJob", "bedrock:InvokeModel"}


def test_both_local_corpora_pass_before_either_is_uploaded(monkeypatch, tmp_path):
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: object())
    monkeypatch.setattr(sync, "resolve_target", lambda *args: ("DATASOURCE", "approved-bucket"))
    checks = iter([{"passed": True}, {"passed": False}])
    monkeypatch.setattr(sync, "prepare_documents", lambda *args, **kwargs: next(checks))
    writes = []
    monkeypatch.setattr(sync, "apply_corpus", lambda *args, **kwargs: writes.append(kwargs))
    with pytest.raises(ValueError, match="policy corpus failed"):
        sync.sync_corpora("EDUCATKB12", "POLICYKB12", "ap-southeast-1", tmp_path)
    assert writes == []
