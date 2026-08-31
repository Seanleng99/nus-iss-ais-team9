import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "final_assessment.py"
SPEC = importlib.util.spec_from_file_location("final_assessment", MODULE_PATH)
assert SPEC and SPEC.loader
final_assessment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(final_assessment)

REPOSITORY_ROOT = Path(__file__).parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "infra/llmsecops/final-assessment-manifest.json"


class FinalAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_repository_manifest_is_complete(self):
        evidence = final_assessment.validate_manifest(
            self.manifest, REPOSITORY_ROOT
        )

        self.assertGreaterEqual(len(evidence), 20)

    def test_report_is_privacy_safe_and_hashes_evidence(self):
        report = final_assessment.build_report(
            MANIFEST_PATH, REPOSITORY_ROOT, self.manifest
        )

        self.assertEqual(report["result"], "pass")
        self.assertEqual(report["data_classification"], "synthetic-data-only")
        self.assertEqual(
            report["evidence_file_count"], len(report["evidence_files"])
        )
        self.assertTrue(
            all(len(item["sha256"]) == 64 for item in report["evidence_files"])
        )

    def test_missing_evidence_file_is_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["requirements"][0]["evidence"][0]["path"] = "missing-file.md"

        with self.assertRaisesRegex(
            final_assessment.AssessmentValidationError, "does not exist"
        ):
            final_assessment.validate_manifest(manifest, REPOSITORY_ROOT)

    def test_duplicate_requirement_id_is_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["requirements"][1]["id"] = manifest["requirements"][0]["id"]

        with self.assertRaisesRegex(
            final_assessment.AssessmentValidationError, "duplicate ids"
        ):
            final_assessment.validate_manifest(manifest, REPOSITORY_ROOT)

    def test_real_data_classification_is_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["project"]["data_classification"] = "personal-financial-data"

        with self.assertRaisesRegex(
            final_assessment.AssessmentValidationError, "synthetic-data-only"
        ):
            final_assessment.validate_manifest(manifest, REPOSITORY_ROOT)

    def test_missing_runbook_section_is_rejected(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["demo_scenarios"][0]["runbook_section"] = "missing-section"

        with self.assertRaisesRegex(
            final_assessment.AssessmentValidationError, "missing runbook section"
        ):
            final_assessment.validate_manifest(manifest, REPOSITORY_ROOT)

    def test_command_writes_json_and_markdown_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assessment.json"
            markdown = Path(directory) / "assessment.md"
            report = final_assessment.build_report(
                MANIFEST_PATH, REPOSITORY_ROOT, self.manifest
            )
            output.write_text(json.dumps(report), encoding="utf-8")
            markdown.write_text(
                final_assessment.render_markdown(report), encoding="utf-8"
            )

            self.assertEqual(json.loads(output.read_text())["result"], "pass")
            self.assertIn("Final assessment evidence", markdown.read_text())


if __name__ == "__main__":
    unittest.main()
