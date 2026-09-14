from pathlib import Path

from cfnlint.decode import decode

ROOT = Path(__file__).resolve().parents[3]


def template(name):
    result, errors = decode(str(ROOT / "infra/aws" / name))
    assert not errors
    return result


def test_database_secret_access_is_isolated_from_frontend_role():
    foundation = template("demo-foundation.yaml")["Resources"]
    role = foundation["BackendTaskRole"]["Properties"]
    statements = role["Policies"][0]["PolicyDocument"]["Statement"]
    assert statements == [{
        "Effect": "Allow",
        "Action": "secretsmanager:GetSecretValue",
        "Resource": {"Fn::GetAtt": ["Database", "MasterUserSecret.SecretArn"]},
    }]
    assert not foundation["AppTaskRole"]["Properties"].get("Policies")
    application = template("demo-application.yaml")
    frontend = application["Resources"]["FrontendTaskDefinition"]["Properties"]
    backend = application["Resources"]["BackendTaskDefinition"]["Properties"]
    assert frontend["TaskRoleArn"] == {"Ref": "AppTaskRoleArn"}
    assert backend["TaskRoleArn"]["Fn::If"] == [
        "HasBackendTaskRole", {"Ref": "BackendTaskRoleArn"}, {"Ref": "AppTaskRoleArn"},
    ]
    assert application["Parameters"]["BackendTaskRoleArn"]["Default"] == ""


def test_pipeline_can_pass_only_the_explicit_optional_backend_role():
    roles = template("github-actions-oidc.yaml")
    statements = roles["Resources"]["DeployRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    pass_role = next(item for item in statements if item["Action"] == "iam:PassRole")
    assert {"Fn::If": [
        "HasBackendTaskRole", {"Ref": "EcsBackendTaskRoleArn"}, {"Ref": "AWS::NoValue"},
    ]} in pass_role["Resource"]
    assert "*" not in pass_role["Resource"]
    assert pass_role["Condition"] == {"StringEquals": {"iam:PassedToService": "ecs-tasks.amazonaws.com"}}
