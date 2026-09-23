import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
RELEASE = ROOT / "published" / "research-six-arm-313f437f"


class InteractiveDemoTest(unittest.TestCase):
    @staticmethod
    def load_demo_data():
        source = (DEMO / "demo-data.js").read_text(encoding="utf-8")
        prefix = "window.TRACER_DEMO = "
        assert source.startswith(prefix) and source.endswith(";\n")
        return json.loads(source[len(prefix):-2])

    def test_static_demo_has_no_external_runtime_dependency(self):
        html = (DEMO / "index.html").read_text(encoding="utf-8")
        for asset in ("styles.css", "demo-data.js", "app.js"):
            self.assertIn(asset, html)
            self.assertTrue((DEMO / asset).is_file())
        self.assertNotIn("<script src=\"http", html)
        self.assertNotIn("<link rel=\"stylesheet\" href=\"http", html)
        self.assertTrue((DEMO / ".nojekyll").is_file())

    def test_demo_aggregate_matches_audited_release(self):
        summary = json.loads((RELEASE / "summary.json").read_text(encoding="utf-8"))
        tasks = sum(row["tasks"] for row in summary["summary"])
        first = sum(row["first"] for row in summary["summary"])
        success = sum(row["success"] for row in summary["summary"])
        data = self.load_demo_data()["evidence"]
        self.assertEqual((tasks, first, success), (864, 735, 811))
        self.assertEqual(data["tasks"], tasks)
        self.assertEqual(data["firstPass"], first)
        self.assertEqual(data["withinThree"], success)
        self.assertEqual(data["recovered"], success - first)

    def test_demo_exposes_all_24_verified_repair_pairs(self):
        benchmark = json.loads((RELEASE / "benchmark.json").read_text(encoding="utf-8"))
        initial = json.loads(
            (RELEASE / "initial_compilation.sanitized.json").read_text(encoding="utf-8")
        )
        trials = [
            json.loads(line)
            for line in (RELEASE / "trials.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        verified_solutions = {
            row["solution"]
            for row in trials
            if row["compile_ok"] and row["independent_compile_ok"] and row.get("solution")
        }
        data = self.load_demo_data()
        cases = data["cases"]
        self.assertEqual(len(cases), 24)
        self.assertEqual({row["id"] for row in cases}, {row["id"] for row in benchmark["problems"]})
        self.assertGreaterEqual(len({row["topic"] for row in cases}), 5)
        self.assertGreaterEqual(len({row["category"] for row in cases}), 4)
        for row in cases:
            with self.subTest(problem=row["id"]):
                self.assertFalse(initial[row["id"]]["compile_ok"])
                self.assertTrue(row["initialProof"].startswith("by"))
                self.assertTrue(row["repairedProof"].strip())
                self.assertTrue((ROOT / row["solutionPath"]).is_file())
                self.assertIn(
                    (ROOT / row["solutionPath"]).relative_to(RELEASE).as_posix(),
                    verified_solutions,
                )

    def test_demo_data_can_be_rebuilt_from_public_release(self):
        generator = (DEMO / "build_demo_data.py").read_text(encoding="utf-8")
        self.assertIn("published", generator)
        self.assertIn("research-six-arm-313f437f", generator)
        self.assertNotIn("requests", generator)

    def test_readmes_offer_web_and_local_demo(self):
        for name in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("runqi-allen-wang.github.io", readme)
                self.assertIn("python demo/serve.py", readme)
                self.assertIn("735/864", readme)
                self.assertIn("811/864", readme)
                self.assertIn("demo/assets/tracer-demo-preview.png", readme)

    def test_pages_workflow_deploys_only_demo_directory(self):
        workflow = (ROOT / ".github" / "workflows" / "demo-pages.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("actions/upload-pages-artifact@v3", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)
        self.assertIn("path: demo", workflow)


if __name__ == "__main__":
    unittest.main()
