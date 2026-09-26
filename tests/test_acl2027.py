import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from acl2027 import (  # noqa: E402
    BENCHMARK_PATH, EXTENDED_CONFIG_PATH, EXTENDED_PREREG_PATH,
    MINIMAX_CONFIG_PATH, MINIMAX_PREREG_PATH, PROTOCOL_PATH,
    audit_readiness, validate_scientific_protocol,
)
from causal_feedback import validate_config, validate_preregistration_record  # noqa: E402
from research import load_benchmark  # noqa: E402


class Acl2027ProtocolTest(unittest.TestCase):
    def test_offline_readiness_freezes_three_independent_families_without_leaks(self):
        report = audit_readiness()
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(report["ready_for_benchmark_run"])
        self.assertEqual(report["network_calls"], 0)
        evidence = report["offline_evidence"]
        self.assertEqual(evidence["test_projects"], 5)
        self.assertEqual(evidence["test_tasks"], 254)
        self.assertEqual(evidence["retrieval_declaration_leaks"], 0)
        self.assertEqual(evidence["independent_model_families"], 3)
        self.assertEqual(evidence["independent_api_origins"], 3)

    def test_nested_call_budgets_are_mechanical(self):
        report = audit_readiness()
        self.assertEqual(report["plans"]["extended"]["maximum_generations"], 13716)
        self.assertEqual(report["plans"]["minimax_confirmatory"]["maximum_generations"], 3048)
        self.assertEqual(report["maximum_total_provider_calls"], 16764)

    def test_frozen_models_are_deepseek_glm_and_minimax_first_party(self):
        extended = validate_config(EXTENDED_CONFIG_PATH)
        minimax = validate_config(MINIMAX_CONFIG_PATH)
        self.assertEqual(
            [(row["model"], row["api_url"]) for row in extended["models"]],
            [
                ("deepseek-v4-pro", "https://api.deepseek.com/chat/completions"),
                ("glm-4.5", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
            ],
        )
        self.assertEqual(
            [(row["model"], row["api_url"]) for row in minimax["models"]],
            [("MiniMax-M3", "https://api.minimax.cn/v1/chat/completions")],
        )
        self.assertIs(minimax["models"][0]["reasoning_split"], True)

    def test_both_runtime_preregistrations_match_runner_contract(self):
        benchmark = load_benchmark(BENCHMARK_PATH)
        for config_path, prereg_path in (
            (EXTENDED_CONFIG_PATH, EXTENDED_PREREG_PATH),
            (MINIMAX_CONFIG_PATH, MINIMAX_PREREG_PATH),
        ):
            config = validate_config(config_path)
            prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
            validate_preregistration_record(prereg, config, benchmark)

    def test_scientific_protocol_rejects_model_family_collapse(self):
        protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
        protocol["model_roles"][1]["family"] = protocol["model_roles"][0]["family"]
        benchmark = load_benchmark(BENCHMARK_PATH)
        extended = validate_config(EXTENDED_CONFIG_PATH)
        minimax = validate_config(MINIMAX_CONFIG_PATH)
        with self.assertRaisesRegex(ValueError, "独立家族"):
            validate_scientific_protocol(protocol, benchmark, extended, minimax)

    def test_preflight_script_clears_all_three_keys_and_runs_audit_first(self):
        script = (ROOT / "scripts/preflight_acl2027.ps1").read_text(encoding="utf-8")
        self.assertLess(
            script.index("src/acl2027.py audit"),
            script.index('Set-HiddenApiKey "DeepSeek API key"'),
        )
        for name in (
            "TRACER_ACL_DEEPSEEK_KEY", "TRACER_ACL_GLM_KEY", "TRACER_ACL_MINIMAX_KEY",
        ):
            self.assertIn("Remove-Item Env:" + name, script)
        self.assertIn('ValidateSet("All", "Extended", "MiniMax")', script)
        self.assertIn('$Provider -in @("All", "MiniMax")', script)
        self.assertNotIn("Write-Output $plainValue", script)

    def test_acl_cli_audit_is_offline_and_successful(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "src/acl2027.py"), "audit"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
