import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from compiler import CANDIDATE_POLICY, lean_subprocess_environment
from export_pilot import reject_secrets, sanitize
from validate_pilot import expected_pairs, validate_runs


class PilotWorkflowTest(unittest.TestCase):
    def test_candidate_environment_isolated_when_scratch_home_is_given(self):
        with tempfile.TemporaryDirectory() as temp:
            env = lean_subprocess_environment(ROOT, Path(temp))
            self.assertEqual(env["TRACER_CANDIDATE_ENV"], "isolated")
            self.assertEqual(Path(env["HOME"]), Path(temp))
            self.assertNotIn("LEAN_PROOF_API_KEY", env)

    def test_policy_is_explicit_and_blocked(self):
        self.assertEqual(CANDIDATE_POLICY["meta_execution"], "blocked")
        self.assertEqual(CANDIDATE_POLICY["environment"], "minimal")

    def test_strict_validator_rejects_missing_pairs(self):
        expected = {("A", "p1")}
        errors = validate_runs([], expected, allow_cache_hits=False)
        self.assertTrue(any("missing" in item for item in errors))

    def test_strict_validator_rejects_cache_hit(self):
        row = {
            "condition": "A", "problem_id": "p1", "run_id": "r1", "round": 1,
            "compile_ok": True, "cache_hit": True, "provider_error": None,
            "diagnostic": {"category": "ok"}, "provider_config": {"provider": "mock"},
            "candidate_policy": CANDIDATE_POLICY, "experiment_id": "e1",
        }
        errors = validate_runs([row], {("A", "p1")}, allow_cache_hits=False)
        self.assertTrue(any("cache" in item for item in errors))

    def test_sanitization_replaces_local_path(self):
        value = sanitize({"source": "C:\\Users\\someone\\repo\\x.lean"}, [("C:\\Users\\someone\\repo", "<repo>")])
        self.assertEqual(value["source"], "<repo>\\x.lean")

    def test_secret_rejection(self):
        with self.assertRaises(ValueError):
            reject_secrets("Authorization: Bearer sk-test-secret-value-1234")

    def test_manifest_has_frozen_pairs(self):
        self.assertEqual(len(expected_pairs(ROOT / "benchmarks" / "manifest.json")), 54)


if __name__ == "__main__":
    unittest.main()
