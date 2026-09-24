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

    def test_current_enrollment_and_sp_metrics_are_ci_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("run: python src/tracer_real_v2.py audit", workflow)
        self.assertIn(
            "run: python src/security_study.py --check published/security-study-tracer-sp-v2/report.json",
            workflow,
        )
        self.assertLess(
            workflow.index("run: python src/tracer_real_v2.py audit"),
            workflow.index("- name: Run tests"),
        )

    def test_published_sp_isolation_evidence_is_a_ci_gate(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        command = (
            "run: python scripts/audit_security_isolation_release.py "
            "published/security-isolation-tracer-sp-v1"
        )
        self.assertIn(command, workflow)
        self.assertLess(workflow.index(command), workflow.index("- name: Run tests"))

    def test_current_six_arm_release_is_audited_before_tests(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        command = (
            "run: python scripts/audit_research_release.py "
            "published/research-six-arm-313f437f"
        )
        self.assertIn(command, workflow)
        self.assertLess(workflow.index(command), workflow.index("- name: Run tests"))
        self.assertNotIn("published/feedback-study-", workflow)
        self.assertNotIn("published/feedback-cross-model-", workflow)
        chart_command = "python scripts/render_six_arm_chart.py"
        chart_diff = "git diff --exit-code -- docs/assets/repair24-six-arm-results.svg"
        self.assertIn(chart_command, workflow)
        self.assertIn(chart_diff, workflow)
        self.assertLess(workflow.index(chart_command), workflow.index("- name: Run tests"))

    def test_lean_action_only_installs_toolchain(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        install_block = workflow.split("- name: Install Lean", 1)[1].split(
            "- name: Install Python dependencies", 1
        )[0]
        self.assertIn("auto-config: false", install_block)
        self.assertIn("use-github-cache: false", install_block)

    def test_superseded_fate_m_workflows_are_archived(self):
        active = ROOT / ".github" / "workflows"
        archived = ROOT / "historical" / "fate_m" / "workflows"
        for name in ("part1.yml", "part1_run.yml", "part2.yml", "part3.yml"):
            self.assertFalse((active / name).exists())
            self.assertTrue((archived / name).is_file())
