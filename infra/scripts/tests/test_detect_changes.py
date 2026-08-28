import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "detect_changes.py"
SPEC = importlib.util.spec_from_file_location("detect_changes", MODULE_PATH)
assert SPEC and SPEC.loader
detect_changes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detect_changes)


class ChangeDetectionTests(unittest.TestCase):
    def test_frontend_change_is_isolated(self):
        result = detect_changes.classify_changes(["apps/frontend/app.py"])

        self.assertTrue(result["frontend_ci"])
        self.assertTrue(result["frontend_deploy"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["backend_deploy"])
        self.assertFalse(result["ai_deploy"])
        self.assertFalse(result["migrations"])

    def test_backend_migration_selects_backend_and_migration(self):
        result = detect_changes.classify_changes(
            ["apps/backend/migrations/versions/002_add_table.py"]
        )

        self.assertTrue(result["backend_ci"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["integration"])
        self.assertTrue(result["migrations"])
        self.assertFalse(result["frontend_deploy"])

    def test_ai_policy_runs_evals_without_deployment(self):
        result = detect_changes.classify_changes(
            ["infra/llmsecops/evaluation-policy.json"]
        )

        self.assertTrue(result["ai_ci"])
        self.assertFalse(result["ai_deploy"])
        self.assertFalse(result["deploy"])

    def test_ai_service_change_redeploys_compatible_backend(self):
        result = detect_changes.classify_changes(["apps/ai-service/app/orchestrator.py"])

        self.assertTrue(result["ai_ci"])
        self.assertTrue(result["ai_deploy"])
        self.assertTrue(result["backend_ci"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["integration"])
        self.assertTrue(result["deploy"])
        self.assertFalse(result["migrations"])

    def test_shared_scan_exception_rebuilds_and_rescans_all_services(self):
        result = detect_changes.classify_changes(
            ["infra/llmsecops/ecr-scan-exceptions.json"]
        )

        self.assertTrue(result["frontend_deploy"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["ai_deploy"])
        self.assertTrue(result["integration"])
        self.assertTrue(result["deploy"])
        self.assertFalse(result["migrations"])

    def test_backend_dockerfile_selects_integration_without_migration(self):
        result = detect_changes.classify_changes(
            ["infra/docker/Dockerfile.backend"]
        )

        self.assertTrue(result["backend_ci"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["integration"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["migrations"])

    def test_ai_dockerfile_redeploys_compatible_backend(self):
        result = detect_changes.classify_changes(
            ["infra/docker/Dockerfile.ai-service"]
        )

        self.assertTrue(result["ai_deploy"])
        self.assertTrue(result["backend_ci"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["integration"])
        self.assertFalse(result["migrations"])

    def test_aws_change_only_runs_infrastructure_validation(self):
        result = detect_changes.classify_changes(["infra/aws/demo-foundation.yaml"])

        self.assertTrue(result["infrastructure"])
        self.assertFalse(result["deploy"])

    def test_operational_script_runs_infrastructure_tests(self):
        result = detect_changes.classify_changes(
            ["infra/scripts/live_evaluation.py"]
        )

        self.assertTrue(result["infrastructure"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["deploy"])

    def test_docs_and_root_readme_do_not_select_service_work(self):
        result = detect_changes.classify_changes(
            ["docs/architecture.md", "README.md"]
        )

        self.assertFalse(any(result.values()))

    def test_workflow_change_selects_all_services_without_migration(self):
        result = detect_changes.classify_changes([".github/workflows/release.yml"])

        self.assertTrue(all(value for key, value in result.items() if key != "migrations"))
        self.assertFalse(result["migrations"])

    def test_model_comparison_workflow_validates_without_service_deployment(self):
        result = detect_changes.classify_changes(
            [".github/workflows/model-comparison.yml"]
        )

        self.assertTrue(result["ai_ci"])
        self.assertTrue(result["infrastructure"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["deploy"])

    def test_rag_governance_workflow_validates_without_service_deployment(self):
        result = detect_changes.classify_changes(
            [".github/workflows/rag-source-governance.yml"]
        )

        self.assertTrue(result["ai_ci"])
        self.assertTrue(result["infrastructure"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["deploy"])

    def test_unknown_change_selects_all_services_without_migration(self):
        result = detect_changes.classify_changes(["shared/runtime-config.toml"])

        self.assertTrue(all(value for key, value in result.items() if key != "migrations"))
        self.assertFalse(result["migrations"])

    def test_force_all_selects_all_ci_without_migration_release(self):
        result = detect_changes.classify_changes([], force_all=True)

        self.assertTrue(all(value for key, value in result.items() if key != "migrations"))
        self.assertFalse(result["migrations"])


if __name__ == "__main__":
    unittest.main()
