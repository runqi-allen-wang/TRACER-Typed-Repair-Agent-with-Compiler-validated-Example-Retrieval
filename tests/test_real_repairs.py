import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from real_repairs import (  # noqa: E402
    PROJECT_SPLITS, assemble_project_benchmark, build_benchmark, declaration_parts,
    marked_source, validate_spec,
)


class RealRepairBuilderTest(unittest.TestCase):
    def test_tracer_real_v1_is_project_disjoint(self):
        root = ROOT / "benchmarks/real_repairs/tracer_real_v1"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "tracer-real-v1")
        self.assertEqual(manifest["split_policy"], "upstream_project_disjoint")
        self.assertEqual(len(manifest["projects"]), 3)
        self.assertEqual(len(manifest["problems"]), 11)
        self.assertEqual({row["split"] for row in manifest["projects"]}, set(PROJECT_SPLITS))
        assignments = {row["project_id"]: row["split"] for row in manifest["projects"]}
        self.assertEqual(len(assignments), 3)
        for problem in manifest["problems"]:
            self.assertEqual(problem["split"], assignments[problem["project_id"]])
            self.assertEqual((root / problem["file"]).read_text(encoding="utf-8"), problem["source_text"])

    def test_published_mathlib_seed_has_three_auditable_tasks(self):
        root = ROOT / "benchmarks/real_repairs/mathlib_v1"
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "tracer-real-mathlib-v1")
        self.assertEqual(manifest["status"], "frozen-real-history")
        self.assertEqual(len(manifest["problems"]), 3)
        self.assertEqual(len({item["id"] for item in manifest["problems"]}), 3)
        for problem in manifest["problems"]:
            self.assertEqual((root / problem["file"]).read_text(encoding="utf-8"), problem["source_text"])
            self.assertNotIn("reference", json.dumps(problem, ensure_ascii=False).lower())
            self.assertTrue(problem["provenance"]["statement_unchanged"])
            self.assertTrue(problem["provenance"]["initial_failure_reproduced"])
            self.assertTrue(problem["provenance"]["fixed_proof_recompiled"])
            self.assertEqual(problem["provenance"]["compile_environment"], "specified_lake_project")

    def test_public_source_rejects_local_or_credentialed_location(self):
        base = {
            "version": "tracer-real-repair-v1", "benchmark_version": "real-v1",
            "source_repository": "local/source", "source_license": "MIT",
            "cases": [{
                "id": "case_one", "before_revision": "before", "fixed_revision": "fixed",
                "file": "Demo.lean", "theorem": "Demo.target",
            }],
        }
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_spec(base)
        base["source_repository"] = "https://token@example.invalid/repo"
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            validate_spec(base)

    def test_declaration_extraction_ignores_delimiter_in_string(self):
        source = '''import Std
namespace Demo
theorem target (x : String := ":=") : True := by
  trivial
@[simp] theorem following : True := by
  trivial
end Demo
'''
        parts = declaration_parts(source, "Demo.target")
        self.assertIn("target", parts["header"])
        self.assertEqual(parts["proof"], "by\n  trivial")
        self.assertNotIn("@[simp]", parts["proof"])
        task = marked_source(source, "Demo.target", "by exact missingName")
        self.assertEqual(task.count("-- PROOF_START"), 1)
        self.assertIn("by exact missingName", task)

    def test_real_git_pair_builds_public_task_and_separate_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "source"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            path = repo / "Demo.lean"
            path.write_text(
                "import Std\n\nnamespace Demo\n\ntheorem repaired (n : Nat) : n = n :=\n  by exact missingName\n\nend Demo\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "Demo.lean"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "broken proof"], cwd=repo, check=True)
            before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            path.write_text(
                "import Std\n\nnamespace Demo\n\ntheorem repaired (n : Nat) : n = n :=\n  by rfl\n\nend Demo\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "add", "Demo.lean"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "repair proof"], cwd=repo, check=True)
            fixed = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            spec = {
                "version": "tracer-real-repair-v1",
                "benchmark_version": "test-real-v1",
                "source_repository": "https://example.invalid/public-repo",
                "source_license": "MIT",
                "cases": [{
                    "id": "demo_repaired", "before_revision": before,
                    "fixed_revision": fixed, "file": "Demo.lean", "theorem": "Demo.repaired",
                }],
            }
            spec_path = root / "spec.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            public, private = root / "public", root / "private"
            result = build_benchmark(repo, spec_path, public, private, timeout=120)
            self.assertEqual(result["tasks"], 1)
            manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
            problem = manifest["problems"][0]
            self.assertTrue(problem["provenance"]["statement_unchanged"])
            self.assertTrue(problem["provenance"]["initial_failure_reproduced"])
            self.assertNotIn("by rfl", problem["source_text"])
            self.assertEqual((private / "demo_repaired.txt").read_text(encoding="utf-8").strip(), "by rfl")
            self.assertFalse((public / "demo_repaired.txt").exists())

    def test_project_assembler_rejects_project_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            tasks = project / "tasks"
            tasks.mkdir(parents=True)
            source = "theorem target : True :=\n  -- PROOF_START\n  by exact missing\n  -- PROOF_END\n"
            (tasks / "one.lean").write_text(source, encoding="utf-8")
            manifest = {
                "version": "one-v1", "status": "test", "license": "MIT",
                "problems": [{
                    "id": "one", "file": "tasks/one.lean", "theorem": "target",
                    "source_text": source,
                    "provenance": {"source_repository": "https://example.invalid/one"},
                }],
            }
            (project / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            spec = {
                "version": "tracer-real-project-split-v1",
                "benchmark_version": "combined-v1",
                "split_policy": "upstream_project_disjoint",
                "projects": [
                    {"project_id": "same", "split": split, "manifest": "project/manifest.json"}
                    for split in PROJECT_SPLITS
                ],
            }
            spec_path = root / "spec.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "项目 ID"):
                assemble_project_benchmark(spec_path, root / "out")


if __name__ == "__main__":
    unittest.main()
