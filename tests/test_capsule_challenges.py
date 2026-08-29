import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "summarize_capsule_challenges.py"
SPEC = importlib.util.spec_from_file_location("summarize_capsule_challenges", SCRIPT)
challenge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(challenge)


class CapsuleChallengeTest(unittest.TestCase):
    def test_four_cases_have_one_changed_source_line_and_theorem_selection(self):
        cases = challenge.discover_cases(ROOT / "gallery_sources" / "challenge")
        self.assertEqual([case["order"] for case in cases], [1, 2, 3, 4])
        for case in cases:
            directory = Path(case["_directory"])
            correct = (directory / case["correct_file"]).read_text(encoding="utf-8").splitlines()
            error = (directory / case["error_file"]).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(correct), len(error), case["case_id"])
            changed = [(left, right) for left, right in zip(correct, error) if left != right]
            self.assertEqual(len(changed), 1, case["case_id"])
            self.assertTrue(case["theorem"])
            self.assertEqual(case["evaluation_set"], "challenge")
            self.assertTrue((directory / "README.md").exists())

    def test_strict_metric_normalizes_noise_but_keeps_later_diagnostics(self):
        left = "/tmp/a.lean:2:4: error: first\n\n/tmp/a.lean:9:1: error: second mvar.12"
        same = "Capsule.lean:20:8: error: first\n\nC:\\work\\b.lean:90:2: error: second mvar.99"
        changed = "C:\\work\\b.lean:20:8: error: first\n\nC:\\work\\b.lean:90:2: error: changed mvar.99"
        self.assertEqual(challenge.strict_ordered_diagnostics(left), challenge.strict_ordered_diagnostics(same))
        self.assertNotEqual(challenge.strict_ordered_diagnostics(left), challenge.strict_ordered_diagnostics(changed))

    def test_summary_counts_challenge_outcomes_without_requiring_all_to_pass(self):
        results = [
            {
                "standalone": True,
                "full_file_fallback": False,
                "official_diagnostic_key_preserved": True,
                "replay_success": True,
                "strict_ordered_diagnostics_preserved": True,
                "pack_elapsed_ms": 10.0,
                "replay_elapsed_ms": 4.0,
            },
            {
                "standalone": False,
                "full_file_fallback": True,
                "official_diagnostic_key_preserved": False,
                "replay_success": False,
                "strict_ordered_diagnostics_preserved": False,
                "pack_elapsed_ms": 20.0,
                "replay_elapsed_ms": 6.0,
            },
        ]
        summary = challenge.summarize(results)
        self.assertEqual(summary["case_count"], 2)
        self.assertEqual(summary["standalone_ratio"], 0.5)
        self.assertEqual(summary["full_file_fallback_ratio"], 0.5)
        self.assertEqual(summary["replay_success_ratio"], 0.5)
        self.assertEqual(summary["average_pack_elapsed_ms"], 15.0)
        self.assertEqual(summary["average_replay_elapsed_ms"], 5.0)

    def test_metadata_is_json_and_contains_no_absolute_paths(self):
        for path in (ROOT / "gallery_sources" / "challenge").glob("*/metadata.json"):
            text = path.read_text(encoding="utf-8")
            metadata = json.loads(text)
            self.assertEqual(metadata["case_id"], path.parent.name)
            self.assertNotIn(str(ROOT), text)

    def test_source_export_does_not_inherit_parent_git_metadata(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(challenge, "ROOT", Path(directory)), \
             patch.object(challenge.subprocess, "run") as run:
            value = challenge._git_value("rev-parse", "HEAD")
        run.assert_not_called()
        self.assertEqual(value, "unavailable (source export without repository metadata)")


if __name__ == "__main__":
    unittest.main()
