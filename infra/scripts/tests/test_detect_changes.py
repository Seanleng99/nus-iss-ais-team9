import importlib.util
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "detect_changes.py"
SPEC = importlib.util.spec_from_file_location("detect_changes", MODULE_PATH)
assert SPEC and SPEC.loader
detect_changes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(detect_changes)


class ChangeDetectionTests(unittest.TestCase):
    def test_shared_language_resources_select_every_service(self):
        result = detect_changes.classify_changes(["apps/shared/coach_i18n/locales/zh-Hans.json"])
        for flag in ("frontend_ci", "backend_ci", "ai_ci",
                     "frontend_deploy", "backend_deploy", "ai_deploy", "integration"):
            self.assertTrue(result[flag], flag)

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
        self.assertTrue(result["ai_ci"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["deploy"])

    def test_post_deploy_smoke_change_runs_a_real_release(self):
        result = detect_changes.classify_changes(
            ["infra/scripts/post_deploy_smoke.py"]
        )

        self.assertTrue(result["integration"])
        self.assertTrue(result["frontend_deploy"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["ai_deploy"])
        self.assertTrue(result["deploy"])
        self.assertFalse(result["migrations"])

    def test_change_classifier_update_runs_a_real_release(self):
        result = detect_changes.classify_changes(["infra/scripts/detect_changes.py"])

        self.assertTrue(result["deploy"])
        self.assertTrue(result["frontend_deploy"])
        self.assertTrue(result["backend_deploy"])
        self.assertTrue(result["ai_deploy"])

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

    def test_investment_agent_workflow_validates_without_service_deployment(self):
        result = detect_changes.classify_changes(
            [".github/workflows/investment-agent-tests.yml"]
        )

        self.assertTrue(result["ai_ci"])
        self.assertTrue(result["infrastructure"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["deploy"])

    def test_assessment_workflows_validate_without_service_deployment(self):
        for path in (
            ".github/workflows/aws-operational-validation.yml",
            ".github/workflows/final-assessment.yml",
        ):
            with self.subTest(path=path):
                result = detect_changes.classify_changes([path])
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

    def test_policy_rag_governance_workflow_validates_without_service_deployment(self):
        result = detect_changes.classify_changes(
            [".github/workflows/policy-rag-source-governance.yml"]
        )

        self.assertTrue(result["ai_ci"])
        self.assertTrue(result["infrastructure"])
        self.assertTrue(result["sast"])
        self.assertFalse(result["deploy"])

    def test_packaged_corpus_change_rebuilds_ai_and_compatible_backend(self):
        for path in (
            "knowledge/investment_education/source_manifest.json",
            "knowledge/policy_controls/documents/advice_boundary.md",
        ):
            with self.subTest(path=path):
                result = detect_changes.classify_changes([path])
                self.assertTrue(result["ai_ci"])
                self.assertTrue(result["infrastructure"])
                self.assertTrue(result["sast"])
                self.assertTrue(result["ai_deploy"])
                self.assertTrue(result["backend_ci"])
                self.assertTrue(result["backend_deploy"])
                self.assertTrue(result["integration"])
                self.assertTrue(result["deploy"])

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
