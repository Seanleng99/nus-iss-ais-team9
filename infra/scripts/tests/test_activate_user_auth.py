from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ACTIVATION_SCRIPT = PROJECT_ROOT / "infra" / "scripts" / "activate_user_auth.ps1"


def test_activation_pins_current_service_images_before_cloudformation_update() -> None:
    script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")

    assert "Get-ServiceTaskDefinition" in script
    assert "Get-ContainerImage" in script
    assert "AiServiceImageUri=$aiImage" in script
    assert "BackendImageUri=$backendImage" in script
    assert "FrontendImageUri=$frontendImage" in script
    assert "--task-definition $migrationBackendTaskDefinition" in script


def test_activation_requires_independently_released_backend_and_frontend_images() -> None:
    script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")

    assert "$backendImage.EndsWith(\":$ExpectedReleaseSha\")" in script
    assert (
        "$frontendImage.EndsWith(\":$ExpectedFrontendReleaseSha\")" in script
    )


def test_activation_clones_an_inactive_deployed_backend_for_migrations() -> None:
    script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")

    assert "function Get-RunnableTaskDefinition" in script
    assert '$definition.status -eq "ACTIVE"' in script
    assert '$definition.status -ne "INACTIVE"' in script
    assert "ecs register-task-definition" in script
    assert "$migrationBackendTaskDefinition = Get-RunnableTaskDefinition" in script


def test_activation_does_not_treat_tolerated_github_cli_warning_as_failure() -> None:
    script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")

    assert '"configure_github.ps1"' in script
    assert "GitHub configuration refresh failed" not in script
