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
            ["leanapap", "pfr", "scilean", "equational_theories", "flt", "physlean"],
        )
        self.assertEqual(
            [row["project_id"] for row in plan["screening_order"]],
            [],
        )
        self.assertEqual(sum(row["candidate_count"] for row in plan["screening_order"]), 0)
        self.assertEqual(
            plan["share_gate_amendment"],
            "experiments/preregistrations/tracer_real_v2_share_gate_amendment2.json",
        )

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
        self.assertEqual(status["screened_before_plan"], 1576)
        reports = {
            path.name.removesuffix(".screen.json"): read_json(path)
            for path in (ROOT / "benchmarks/real_repairs/tracer_real_v2_screening").glob("*.screen.json")
        }
        self.assertEqual(
            status["remaining_candidates"],
            1576 - sum(report["candidates"] for report in reports.values()),
        )
        expected_next = next(
            (row["project_id"] for row in read_json(PLAN_PATH)["screening_order"]
             if row["project_id"] not in reports),
            None,
        )
        self.assertEqual(status["next_project"], expected_next)
        projection = status["enrollment_projection"]
        self.assertEqual(projection["screened_projects"], len(reports))
        qualifying = [report for report in reports.values() if report["accepted"] >= 5]
        self.assertEqual(projection["qualifying_test_projects"], len(qualifying))
        # SciLean 有 2 个通过项，但未达到项目级 5 题门槛，不能进入暂定合格池。
        self.assertEqual(reports["scilean"]["accepted"], 2)
        self.assertEqual(
            projection["provisional_accepted_repairs"],
            sum(report["accepted"] for report in qualifying),
        )
        self.assertEqual(
            projection["additional_qualifying_projects_needed"],
            max(0, 5 - len(qualifying)),
        )
        self.assertEqual(projection["ready_to_assemble"], status["remaining_candidates"] == 0 and all(
            projection["gates"].values()
        ))

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
        self.assertIn("& lake build", script)
        self.assertIn('$env:LEAN_NUM_THREADS = "1"', script)
        self.assertNotIn("lake update", script.replace("`lake update`", ""))
        self.assertIn("缺少已提交的 lake-manifest.json", script)
        self.assertIn("& lake env lean $probeSource", script)
        self.assertIn("冻结源码探针不能在项目环境中编译", script)
        self.assertIn('.lake\\build\\lib\\lean', script)
        self.assertIn("src/real_repairs.py build", script)
        self.assertIn("private_references", script)
        self.assertNotIn("LEAN_PROOF_API_KEY", script)
        self.assertNotIn("TRACER_RESEARCH_API_KEY", script)


if __name__ == "__main__":
    unittest.main()
