import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tracer_real_v2_screening_plan import PLAN_PATH, build_status, read_json, validate_plan


class TracerRealV2ScreeningPlanTest(unittest.TestCase):
    def test_plan_exactly_covers_completed_and_remaining_projects(self):
        plan = read_json(PLAN_PATH)
        validate_plan(plan)
        self.assertEqual(
            [row["project_id"] for row in plan["completed_before_plan"]],
            ["leanapap", "pfr"],
        )
        self.assertEqual(
            [row["project_id"] for row in plan["screening_order"]],
            ["scilean", "equational_theories", "flt", "physlean"],
        )
        self.assertEqual(sum(row["candidate_count"] for row in plan["screening_order"]), 1249)

    def test_plan_is_single_worker_resumable_and_provider_free(self):
        plan = read_json(PLAN_PATH)
        self.assertFalse(plan["provider_calls_allowed"])
        self.assertEqual(plan["execution"]["workers"], 1)
        self.assertTrue(plan["execution"]["checkpoint_after_each_candidate"])
        self.assertTrue(plan["execution"]["refuse_while_research_runner_active"])

    def test_status_reports_no_heavy_work_or_provider_claim(self):
        status = build_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["provider_calls"], 0)
        self.assertEqual(status["screened_before_plan"], 327)
        self.assertEqual(status["remaining_candidates"], 1249)
        self.assertEqual(status["next_project"], "scilean")
        projection = status["enrollment_projection"]
        self.assertEqual(projection["screened_projects"], 2)
        self.assertEqual(projection["qualifying_test_projects"], 2)
        self.assertEqual(projection["provisional_accepted_repairs"], 60)
        self.assertEqual(projection["provisional_error_categories"], [
            "compile_error", "type_mismatch", "unknown_identifier", "unsolved_goals",
        ])
        self.assertEqual(projection["additional_qualifying_projects_needed"], 3)
        self.assertEqual(projection["minimum_additional_tasks_for_current_largest_share"], 66)
        self.assertFalse(projection["ready_to_assemble"])

    def test_powershell_entry_refuses_concurrent_research(self):
        script_path = ROOT / "scripts/run_tracer_real_v2_screening.ps1"
        self.assertTrue(script_path.read_bytes().startswith(b"\xef\xbb\xbf"))
        script = script_path.read_text(encoding="utf-8-sig")
        self.assertIn("Test-ActiveResearchRunner", script)
        self.assertIn("LastWriteTimeUtc", script)
        self.assertIn("AddMinutes(-15)", script)
        self.assertIn("TRACER_V2_CONCURRENT_RESEARCH", script)
        self.assertIn("拒绝启动 V2", script)
        self.assertIn("--workers 1", script)
        self.assertIn('"Status", "Prepare", "Screen", "Build"', script)
        self.assertIn("src/real_repairs.py build", script)
        self.assertIn("private_references", script)
        self.assertNotIn("LEAN_PROOF_API_KEY", script)
        self.assertNotIn("TRACER_RESEARCH_API_KEY", script)


if __name__ == "__main__":
    unittest.main()
