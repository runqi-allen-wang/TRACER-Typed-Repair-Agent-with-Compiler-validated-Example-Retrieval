import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContinuousIntegrationTest(unittest.TestCase):
    def test_mathlib_setup_has_retry_and_timeout_without_ignoring_failure(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        setup_block = workflow.split("- name: Prepare Mathlib dependency project", 1)[1].split(
            "- name: Replay public capsules", 1
        )[0]
        self.assertIn("timeout-minutes: 30", setup_block)
        self.assertIn('TRACER_SETUP_ATTEMPTS: "3"', setup_block)
        self.assertNotIn("continue-on-error", setup_block)
        self.assertNotIn("|| true", setup_block)

    def test_lean_is_installed_before_end_to_end_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("- name: Install Lean"), workflow.index("- name: Run tests"))

    def test_lean_project_is_built_before_end_to_end_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("- name: Build Lean project"), workflow.index("- name: Run tests"))

    def test_lean_action_only_installs_toolchain(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        install_block = workflow.split("- name: Install Lean", 1)[1].split(
            "- name: Install Python dependencies", 1
        )[0]
        self.assertIn("auto-config: false", install_block)
        self.assertIn("use-github-cache: false", install_block)

    def test_part2_workflow_contract(self):
        workflow = (ROOT / ".github" / "workflows" / "part2.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("ubuntu-latest", workflow)
        self.assertNotIn("windows-latest", workflow)
        self.assertIn("tests.test_feedback", workflow)
        self.assertIn("tests.test_ax_integration", workflow)
        self.assertIn("validate_axprover_contract.py", workflow)
        self.assertIn("06dfadc9ab439755af5efcfe0add95bfef2733c7", workflow)
        self.assertIn("pip install /tmp/ax-prover-base", workflow)
        self.assertIn("smoke_axprover_integration.py", workflow)
        self.assertIn("python scripts/run_ci_tests.py", workflow)
        self.assertIn("run: lake build", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("secrets.", workflow)
