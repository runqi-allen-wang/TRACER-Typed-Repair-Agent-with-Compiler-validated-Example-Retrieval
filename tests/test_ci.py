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

    def test_capsule_feasibility_gate_runs_in_ci(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        gate = "- name: Run Capsule feasibility gate"
        self.assertIn(gate, workflow)
        self.assertIn("run: python scripts/run_capsule_feasibility.py", workflow)
        self.assertLess(workflow.index("- name: Build Lean project"), workflow.index(gate))

    def test_compiler_feedback_v1_gate_runs_after_lean_build(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        gate = "- name: Verify Compiler Feedback v1 fixtures"
        self.assertIn(gate, workflow)
        self.assertIn(
            "run: python scripts/verify_compiler_feedback_v1.py --verify-only",
            workflow,
        )
        self.assertLess(workflow.index("- name: Build Lean project"), workflow.index(gate))
        self.assertLess(workflow.index(gate), workflow.index("- name: Run tests"))

    def test_feedback_plan_and_sp_metrics_are_ci_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("run: python src/feedback_study.py plan", workflow)
        self.assertIn("run: python src/tracer_real_v2.py audit", workflow)
        self.assertIn(
            "run: python src/security_study.py --check published/security-study-tracer-sp-v2/report.json",
            workflow,
        )
        self.assertLess(
            workflow.index("run: python src/feedback_study.py plan"),
            workflow.index("- name: Run tests"),
        )
        self.assertLess(
            workflow.index("run: python src/tracer_real_v2.py audit"),
            workflow.index("- name: Run tests"),
        )

    def test_published_feedback_study_is_audited_before_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        commands = [
            "run: python scripts/audit_feedback_study.py "
            "published/feedback-study-8ccb89dd-3e26-47f0-8eae-d1930b95e248",
            "run: python scripts/audit_feedback_study.py "
            "published/feedback-study-562ad440-3446-4138-801e-59726ed0e108",
            "run: python scripts/audit_feedback_comparison.py "
            "published/feedback-cross-model-8ccb89dd-562ad440",
        ]
        for command in commands:
            self.assertIn(command, workflow)
            self.assertLess(workflow.index(command), workflow.index("- name: Run tests"))

    def test_second_model_replication_contract_is_checked_before_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        command = (
            "run: python scripts/plan_feedback_replication.py --model-id ci-second-model "
            "--api-url https://example.invalid/v1/chat/completions --model ci-second-model"
        )
        self.assertIn(command, workflow)
        self.assertLess(workflow.index(command), workflow.index("- name: Run tests"))

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

    def test_part1_pin_check_does_not_depend_on_remote_ref_listing(self):
        workflow = (ROOT / ".github" / "workflows" / "part1.yml").read_text(encoding="utf-8")
        self.assertIn("Check immutable ax-prover dependency pin", workflow)
        self.assertIn("requirements-axprover-part2.txt", workflow)
        self.assertIn("06dfadc9ab439755af5efcfe0add95bfef2733c7", workflow)
        self.assertNotIn("git ls-remote", workflow)

    def test_part3_workflow_validates_b_handoff(self):
        workflow = (ROOT / ".github" / "workflows" / "part3.yml").read_text(encoding="utf-8")
        self.assertIn("results/handoff/part2-experience-capsule-20260829/**", workflow)
        self.assertIn("scripts/validate_b_handoff.py", workflow)
        self.assertIn("run: python scripts/validate_b_handoff.py", workflow)
        self.assertLess(
            workflow.index("run: python scripts/validate_part3_handoff.py"),
            workflow.index("run: python scripts/validate_b_handoff.py"),
        )
