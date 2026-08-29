"""参考证明只用于离线题库验收，生产运行器不读取此目录。"""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from compiler import compile_candidate


class RepairBenchmarkTest(unittest.TestCase):
    def test_all_initial_repairs_fail_and_references_compile(self):
        base = ROOT / "benchmarks/repair24"
        manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
        references = json.loads((ROOT / "tests/fixtures/repair24_reference.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["problems"]), 24)
        self.assertEqual({p["id"] for p in manifest["problems"]}, set(references))
        for problem in manifest["problems"]:
            with self.subTest(problem=problem["id"]):
                path = base / problem["file"]
                source = path.read_text(encoding="utf-8")
                self.assertEqual(source, problem["source_text"])
                bad = source.split("-- PROOF_START")[1].split("-- PROOF_END")[0]
                kwargs = dict(source_path=path, source=source, theorem_name=problem["theorem"], timeout=float(os.environ.get("TRACER_TEST_LEAN_TIMEOUT", "60")))
                initial = compile_candidate(candidate=bad, **kwargs)
                self.assertIsNotNone(initial.returncode, initial.diagnostics)
                self.assertFalse(initial.ok, problem["id"] + " 初始候选已经成功")
                fixed = compile_candidate(candidate=references[problem["id"]], **kwargs)
                self.assertTrue(fixed.ok, fixed.diagnostics)
