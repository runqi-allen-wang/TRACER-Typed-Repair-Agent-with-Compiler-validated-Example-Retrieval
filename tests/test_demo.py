import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
RELEASE = ROOT / "published" / "research-six-arm-313f437f"


class InteractiveDemoTest(unittest.TestCase):
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
        data = (DEMO / "demo-data.js").read_text(encoding="utf-8")
        self.assertEqual((tasks, first, success), (864, 735, 811))
        for fragment in (
            f"tasks: {tasks}",
            f"firstPass: {first}",
            f"withinThree: {success}",
            f"recovered: {success - first}",
        ):
            self.assertIn(fragment, data)

    def test_demo_trace_is_a_real_two_round_success(self):
        attempts = [
            json.loads(line)
            for line in (RELEASE / "attempts.sanitized.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        trace = sorted(
            (
                row for row in attempts
                if row["model_id"] == "deepseek_flash_v41"
                and row["repeat"] == 1
                and row["arm"] == "C_dynamic"
                and row["problem_id"] == "scale_add"
            ),
            key=lambda row: row["round"],
        )
        self.assertEqual([row["compile_ok"] for row in trace], [False, True])
        data = (DEMO / "demo-data.js").read_text(encoding="utf-8")
        self.assertIn("rw [ih, Nat.add_assoc]", data)
        self.assertIn("change scale a (m + n) + a", data)
        self.assertIn("Did not find an occurrence", data)
        self.assertIn("score 0.3760", data)
        self.assertIn("score 0.5199", data)

    def test_readmes_offer_web_and_local_demo(self):
        for name in ("README.md", "README.zh-CN.md"):
            readme = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIn("runqi-allen-wang.github.io", readme)
                self.assertIn("python demo/serve.py", readme)
                self.assertIn("735/864", readme)
                self.assertIn("811/864", readme)

    def test_pages_workflow_deploys_only_demo_directory(self):
        workflow = (ROOT / ".github" / "workflows" / "demo-pages.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("actions/upload-pages-artifact@v3", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)
        self.assertIn("path: demo", workflow)


if __name__ == "__main__":
    unittest.main()
