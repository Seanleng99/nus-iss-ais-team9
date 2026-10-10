from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FOUNDATION_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "demo-foundation.yaml"
APPLICATION_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "demo-application.yaml"
HARDENING_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "harden_edge.ps1"
BOOTSTRAP_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "bootstrap_demo.ps1"
AUTH_ACTIVATION_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "activate_user_auth.ps1"


def test_foundation_restricts_origin_and_supports_modern_custom_domain() -> None:
    template = FOUNDATION_TEMPLATE.read_text(encoding="utf-8")

    assert "com.amazonaws.global.cloudfront.origin-facing" in template
    assert template.count("SourcePrefixListId:") == 1
    assert "ToPort: !If [HasCloudFrontOriginPrefixList, 443, 80]" in template
    assert "CloudFrontOriginSecret" in template
    assert "HeaderName: X-Coach-Origin-Verify" in template
    assert "OriginProtocolPolicy: !If [HasCustomDomain, https-only, http-only]" in template
    assert "MinimumProtocolVersion: TLSv1.2_2021" in template
    assert "Type: AWS::Route53::RecordSet" in template


def test_application_denies_missing_origin_header_on_http_and_https() -> None:
    template = APPLICATION_TEMPLATE.read_text(encoding="utf-8")

    assert template.count("MessageBody: '{\"detail\":\"Origin access denied\"}'") == 2
    assert template.count("HttpHeaderName: X-Coach-Origin-Verify") == 4
    assert "SslPolicy: ELBSecurityPolicy-TLS13-1-2-2021-06" in template
    assert "CloudFrontOriginSecretArn" in template


def test_hardening_script_has_staged_domain_rollout_and_release_guards() -> None:
    script = HARDENING_SCRIPT.read_text(encoding="utf-8")

    assert "HARDEN-EDGE" in script
    assert "com.amazonaws.global.cloudfront.origin-facing" in script
    assert "The deployed backend image" in script
    assert "Preparing the HTTPS origin listener before switching CloudFront" in script
    assert "Activating the custom CloudFront domain and HTTPS origin" in script
    assert "edge_security_validation.py" in script


def test_existing_deployment_paths_supply_origin_restriction_contract() -> None:
    for path in (BOOTSTRAP_SCRIPT, AUTH_ACTIVATION_SCRIPT):
        script = path.read_text(encoding="utf-8")
        assert "com.amazonaws.global.cloudfront.origin-facing" in script
        assert "CloudFrontOriginPrefixListId=" in script
        assert "CloudFrontOriginSecretArn=" in script


def test_backend_reservations_match_ai_budget_and_expose_quota_monitoring():
    import shlex

    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_multi_constructor("!", lambda loader, tag, node: loader.construct_scalar(node)
                                 if isinstance(node, yaml.ScalarNode) else
                                 loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
                                 else loader.construct_mapping(node))
    resources = yaml.load(APPLICATION_TEMPLATE.read_text(encoding="utf-8"), Loader=Loader)["Resources"]
    environments = {}
    for name in ("BackendTaskDefinition", "AiTaskDefinition"):
        container = resources[name]["Properties"]["ContainerDefinitions"][0]
        environments[name] = {item["Name"]: item["Value"] for item in container["Environment"] if "Name" in item}
    assert environments["BackendTaskDefinition"]["MAX_MODEL_TOKENS_PER_RUN"] == environments["AiTaskDefinition"]["MAX_MODEL_TOKENS_PER_RUN"]
    assert int(environments["BackendTaskDefinition"]["COACH_CONCURRENT_REQUESTS"]) == 2
    # The integration test shares one automation credential across every
    # synthetic profile, so its parallelism must respect that principal's cap.
    workflow = yaml.safe_load((PROJECT_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["service-integration"]["steps"]
    command = shlex.split(next(step["run"] for step in steps if step.get("name") == "Verify bounded concurrency"))
    concurrency = int(command[command.index("--concurrency") + 1])
    assert concurrency <= int(environments["BackendTaskDefinition"]["COACH_CONCURRENT_REQUESTS"])
    assert resources["CoachQuotaDeniedMetricFilter"]["Properties"]["LogGroupName"] == "BackendLogGroupName"
    assert resources["CoachQuotaDeniedAlarm"]["Properties"]["MetricName"] == "CoachQuotaDenials"
    assert resources["CoachModelTokensMetricFilter"]["Properties"]["MetricTransformations"][0]["MetricValue"] == "$.total_tokens"
