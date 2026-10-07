from pathlib import Path

from cfnlint.decode import decode

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_TEMPLATE = PROJECT_ROOT / "infra" / "aws" / "demo-application.yaml"


def test_backend_adapts_upstream_metadata_and_frontend_uses_adapter() -> None:
    template = APPLICATION_TEMPLATE.read_text(encoding="utf-8")

    assert "OIDC_METADATA_PROXY_ENABLED" in template
    assert "Value: !Ref OidcServerMetadataUrl" in template
    assert 'Value: !Sub "${FrontendUrl}/api/oidc/metadata"' in template


def test_frontend_tokens_allow_three_hour_sessions():
    foundation, errors = decode(str(PROJECT_ROOT / "infra/aws/demo-foundation.yaml"))
    assert not errors
    client = foundation["Resources"]["FrontendUserPoolClient"]["Properties"]
    assert client["IdTokenValidity"] == client["AccessTokenValidity"] == 3
    assert client["TokenValidityUnits"]["IdToken"] == "hours"
    assert client["TokenValidityUnits"]["AccessToken"] == "hours"
