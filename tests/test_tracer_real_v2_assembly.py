import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tracer_real_v2_assembly import assembly_status, compose_project_spec, read_json


class TracerRealV2AssemblyTest(unittest.TestCase):
    def test_assembly_status_tracks_screening_and_public_subsets(self):
        status = assembly_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["provider_calls"], 0)
        self.assertIn("flt", status["qualifying_test_projects"])
        self.assertNotIn("scilean", status["qualifying_test_projects"])
        physlean_report = ROOT / "benchmarks/real_repairs/tracer_real_v2_screening/physlean.screen.json"
        if not physlean_report.exists():
            self.assertFalse(status["ready"])
            self.assertTrue(any("physlean" in blocker for blocker in status["blockers"]))
            self.assertFalse(any("缺少已验证公开子题库" in blocker for blocker in status["blockers"]))
            self.assertFalse(any("公开子题库无效" in blocker for blocker in status["blockers"]))
            self.assertIsNone(status["project_spec"])
            self.assertIsNone(status["next_command"])
        elif any("maximum_test_project_share" in blocker for blocker in status["blockers"]):
            self.assertFalse(status["ready"])
            self.assertIsNone(status["project_spec"])
            self.assertIsNone(status["next_command"])
        elif status["ready"]:
            self.assertFalse(status["blockers"])
            self.assertIsNotNone(status["project_spec"])
            self.assertIsNotNone(status["next_command"])

    def test_six_project_screening_uses_disclosed_share_gate_revision(self):
        physlean_report = ROOT / "benchmarks/real_repairs/tracer_real_v2_screening/physlean.screen.json"
        if not physlean_report.exists():
            self.skipTest("PhysLean 全量筛查尚未完成")
        status = assembly_status()
        projection = status["enrollment_projection"]
        self.assertAlmostEqual(projection["current_largest_project_share"], 94 / 254)
        self.assertTrue(projection["gates"]["maximum_test_project_share"])
        self.assertTrue(status["ready"])
        self.assertIsNotNone(status["project_spec"])

    def test_write_spec_matches_current_gate(self):
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "forbidden.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "src/tracer_real_v2_assembly.py"),
                 "write-spec", "--out", str(out)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            if assembly_status()["ready"]:
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertTrue(out.exists())
            else:
                self.assertEqual(completed.returncode, 1)
                self.assertFalse(out.exists())
                self.assertIn("尚未就绪", completed.stdout)

    def test_composed_spec_keeps_v1_out_of_test_and_new_projects_in_test(self):
        plan = read_json(ROOT / "experiments/tracer_real_v2_screening.plan.json")
        contract = read_json(ROOT / plan["enrollment_contract"])
        inventory = read_json(ROOT / plan["candidate_inventory"])
        spec = compose_project_spec(
            contract, inventory,
            ["leanapap", "physlean", "equational_theories", "flt", "pfr", "scilean"],
        )
        split = {row["project_id"]: row["split"] for row in spec["projects"]}
        self.assertEqual(split["mathlib"], "development")
        self.assertEqual(split["batteries"], "validation")
        self.assertEqual(split["aesop"], "validation")
        for project_id in ("leanapap", "physlean", "equational_theories", "flt", "pfr", "scilean"):
            self.assertEqual(split[project_id], "test")
        self.assertEqual(len(spec["projects"]), 9)


if __name__ == "__main__":
    unittest.main()
