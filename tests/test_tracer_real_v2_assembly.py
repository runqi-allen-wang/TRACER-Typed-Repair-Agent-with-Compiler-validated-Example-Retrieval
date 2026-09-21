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
    def test_current_incomplete_screening_cannot_emit_final_spec(self):
        status = assembly_status()
        self.assertTrue(status["ok"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["provider_calls"], 0)
        self.assertTrue(any("scilean" in blocker for blocker in status["blockers"]))
        self.assertIsNone(status["project_spec"])
        self.assertIsNone(status["next_command"])

    def test_write_spec_fails_closed_without_creating_output(self):
        with tempfile.TemporaryDirectory() as raw:
            out = Path(raw) / "forbidden.json"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "src/tracer_real_v2_assembly.py"),
                 "write-spec", "--out", str(out)],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
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
