import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from real_repair_inventory import (  # noqa: E402
    _append_screen_state, _load_screen_state, declaration_names, scan_history, screen_inventory,
)


class RealRepairInventoryTest(unittest.TestCase):
    def _commit(self, repo: Path, message: str) -> str:
        subprocess.run(["git", "add", "Demo.lean"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", message],
            cwd=repo,
            check=True,
        )
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    def test_declaration_names_preserve_namespace(self):
        source = "namespace Outer\nnamespace Inner\ntheorem target : True := by trivial\nend Inner\nend Outer\n"
        self.assertEqual(declaration_names(source), ["Outer.Inner.target"])

    def test_scan_is_deterministic_and_uses_fixed_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            path = repo / "Demo.lean"
            path.write_text("namespace Demo\ntheorem target : True := by exact missing\nend Demo\n", encoding="utf-8")
            before = self._commit(repo, "old proof")
            path.write_text("namespace Demo\ntheorem target : True := by trivial\nend Demo\n", encoding="utf-8")
            fixed = self._commit(repo, "repair proof")
            inventory = scan_history(
                repo,
                project_id="demo",
                source_repository="https://example.invalid/demo",
                source_license="MIT",
                max_commits=10,
            )
            self.assertEqual(inventory["endpoint_revision"], fixed)
            self.assertEqual(len(inventory["candidates"]), 1)
            candidate = inventory["candidates"][0]
            self.assertEqual(candidate["before_revision"], before)
            self.assertEqual(candidate["fixed_revision"], fixed)
            self.assertEqual(candidate["theorem"], "Demo.target")

    def test_screen_records_every_acceptance_and_rejection(self):
        inventory = {
            "version": "tracer-real-candidate-inventory-v1",
            "project_id": "demo",
            "source_repository": "https://example.invalid/demo",
            "source_license": "MIT",
            "endpoint_revision": "fixed",
            "candidates": [
                {"id": "demo_good", "before_revision": "a", "fixed_revision": "fixed", "file": "A.lean", "theorem": "good"},
                {"id": "demo_bad", "before_revision": "b", "fixed_revision": "fixed", "file": "B.lean", "theorem": "bad"},
            ],
        }

        def fake_build(_repo, _spec, item, _timeout, _project_root):
            if item["id"] == "demo_bad":
                raise ValueError("旧证明仍然通过")
            return ({"expected_error": "unknown_identifier"}, "by trivial")

        with patch("real_repair_inventory.build_case", side_effect=fake_build):
            spec, report = screen_inventory(Path.cwd(), inventory, project_root=None, timeout=1)
        self.assertEqual([row["id"] for row in spec["cases"]], ["demo_good"])
        self.assertEqual(report["accepted"], 1)
        self.assertEqual(report["rejected"], 1)
        self.assertEqual(len(report["decisions"]), 2)
        self.assertIn("旧证明仍然通过", report["decisions"][1]["reason"])

    def test_screen_state_resumes_without_recompiling_and_rejects_drift(self):
        inventory = {
            "version": "tracer-real-candidate-inventory-v1",
            "project_id": "demo",
            "source_repository": "https://example.invalid/demo",
            "source_license": "MIT",
            "endpoint_revision": "fixed",
            "candidates": [{
                "id": "demo_one", "before_revision": "old", "fixed_revision": "fixed",
                "file": "Demo.lean", "theorem": "Demo.one",
            }],
        }
        item = {key: inventory["candidates"][0][key] for key in ("id", "before_revision", "fixed_revision", "file", "theorem")}
        decision = {
            "candidate": item,
            "outcome": {"id": "demo_one", "accepted": True, "error_category": "unknown_identifier"},
        }
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.jsonl"
            _append_screen_state(state, decision)
            completed = _load_screen_state(state)
            with patch("real_repair_inventory.build_case") as build:
                spec, report = screen_inventory(
                    Path.cwd(), inventory, project_root=None, timeout=1, completed=completed,
                )
            build.assert_not_called()
            self.assertEqual(len(spec["cases"]), 1)
            self.assertEqual(report["accepted"], 1)
            drifted = json.loads(json.dumps(inventory))
            drifted["candidates"][0]["file"] = "Changed.lean"
            with self.assertRaisesRegex(ValueError, "不一致"):
                screen_inventory(Path.cwd(), drifted, project_root=None, timeout=1, completed=completed)

    def test_parallel_screen_keeps_frozen_order_and_serializes_checkpoints(self):
        inventory = {
            "version": "tracer-real-candidate-inventory-v1",
            "project_id": "demo",
            "source_repository": "https://example.invalid/demo",
            "source_license": "MIT",
            "endpoint_revision": "fixed",
            "candidates": [
                {
                    "id": f"demo_{index}", "before_revision": f"old-{index}",
                    "fixed_revision": "fixed", "file": f"Demo{index}.lean", "theorem": f"Demo.t{index}",
                }
                for index in range(6)
            ],
        }
        recorded = []

        def fake_build(_repo, _spec, item, _timeout, _project_root):
            if item["id"] == "demo_3":
                raise ValueError("历史证明未形成失败")
            return ({"expected_error": "type_mismatch"}, "by trivial")

        with patch("real_repair_inventory.build_case", side_effect=fake_build):
            spec, report = screen_inventory(
                Path.cwd(), inventory, project_root=None, timeout=1,
                on_decision=recorded.append, workers=3,
            )
        self.assertEqual(len(recorded), 6)
        self.assertEqual(len({row["candidate"]["id"] for row in recorded}), 6)
        self.assertEqual([row["id"] for row in report["decisions"]], [f"demo_{index}" for index in range(6)])
        self.assertEqual([row["id"] for row in spec["cases"]], [
            "demo_0", "demo_1", "demo_2", "demo_4", "demo_5",
        ])

    def test_screen_rejects_nonpositive_workers(self):
        inventory = {
            "version": "tracer-real-candidate-inventory-v1",
            "project_id": "demo",
            "source_repository": "https://example.invalid/demo",
            "source_license": "MIT",
            "endpoint_revision": "fixed",
            "candidates": [],
        }
        with self.assertRaisesRegex(ValueError, "workers"):
            screen_inventory(Path.cwd(), inventory, project_root=None, timeout=1, workers=0)


if __name__ == "__main__":
    unittest.main()
