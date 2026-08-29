"""跨系统工件、真人研究和付费保护入口的离线回归；替身计时不是人类数据。"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from human_study import assignment, report, run_session, valid_answer
from research import CallBudget, load_config, prompt_api_keys, write_json
from provider import OpenAICompatibleProvider
from stage_cross_os import stage


class ResearchExecutionTest(unittest.TestCase):
    def test_human_cases_complement_between_participants_not_within(self):
        materials = {"cases": [{"case_id": str(i)} for i in range(8)]}
        a, b = assignment(materials, 1), assignment(materials, 2)
        self.assertEqual(len({r["case_id"] for r in a}), 8)
        self.assertEqual(sum(r["representation"] == "original" for r in a), 4)
        self.assertTrue(all(x["case_id"] == y["case_id"] and x["representation"] != y["representation"] for x, y in zip(a, b)))

    def test_placeholder_answers_are_not_observations(self):
        for answer in ("", "错误位置＋原因", "错误位置 + 原因", "PASS"):
            self.assertFalse(valid_answer(answer))
        self.assertTrue(valid_answer("第八行引用的标识符未在本命名空间中声明"))

    def test_human_timer_does_not_include_answer_typing_and_rejects_reuse(self):
        materials = {"version": "test-only", "cases": [{"case_id": "c", "original_source": "long source", "capsule_source": "short source"}]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "materials.json", materials)
            with patch("builtins.input", side_effect=["YES", "basic", "", "", "no", "错误位置＋原因", "第八行引用的标识符未在本命名空间中声明"]), \
                 patch("human_study.time.perf_counter", side_effect=[10, 14]):
                run_session(root / "materials.json", root / "run", 1)
            rows = [json.loads(s) for s in (root / "run/p01/responses.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["elapsed_seconds"], 4)
            self.assertEqual(rows[0]["correctness"], "pending")
            with self.assertRaises(ValueError):
                run_session(root / "materials.json", root / "run", 1)
            result = report(root / "run", root / "materials.json")
            self.assertEqual(result["pending_reviews"], 1)
            self.assertFalse(result["human_review_complete"])

    def test_declining_creates_no_human_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "m.json", {"cases": [{"case_id": "one"}]})
            with patch("builtins.input", return_value="no"):
                self.assertFalse(run_session(root / "m.json", root / "run", 1)["started"])
            self.assertFalse(list(root.rglob("responses.jsonl")))

    def test_call_budget_reserves_before_dispatch_and_does_not_refund(self):
        model = {"input_price_per_1k": 1, "output_price_per_1k": 1, "max_tokens": 1}
        guard = CallBudget(1, 10)
        guard.reserve("test", model)
        self.assertEqual(guard.calls, 1)
        with tempfile.TemporaryDirectory() as directory:
            saved = CallBudget(2, 10)
            saved.ledger_path = Path(directory) / "budget.json"
            saved.reserve("test", model)
            self.assertEqual(json.loads(saved.ledger_path.read_text(encoding="utf-8"))["attempted_calls"], 1)
        with self.assertRaises(RuntimeError):
            guard.reserve("again", model)
        self.assertEqual(guard.calls, 1)
        with self.assertRaises(RuntimeError):
            CallBudget(10, 0.001).reserve("prompt", model)
        with self.assertRaises(ValueError):
            CallBudget(10, 1).reserve("prompt", dict(model, input_price_per_1k=None))

    def test_one_secret_prompt_per_origin_not_stored_in_environment(self):
        config = load_config(ROOT / "experiments/research.deepseek.json")
        previous = dict(os.environ)
        with patch("research.sys.stdin.isatty", return_value=True), patch("research.getpass.getpass", return_value="test-only-not-a-key") as prompt:
            keys = prompt_api_keys(config)
        self.assertEqual(prompt.call_count, 1)
        self.assertEqual(len(keys), 1)
        self.assertEqual(dict(os.environ), previous)

    def test_secret_prompt_refuses_non_interactive_fallback(self):
        config = load_config(ROOT / "experiments/research.deepseek.json")
        with patch("research.sys.stdin.isatty", return_value=False), patch("research.getpass.getpass") as prompt:
            with self.assertRaises(ValueError):
                prompt_api_keys(config)
            prompt.assert_not_called()

    def test_shared_secret_rejects_different_origins(self):
        config = load_config(ROOT / "experiments/research.deepseek.json")
        config["models"][1]["api_url"] = "https://other.invalid/chat/completions"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            write_json(path, config)
            with self.assertRaisesRegex(ValueError, "不同 API 来源"):
                load_config(path)

    def test_provider_records_and_sends_explicit_thinking(self):
        provider = OpenAICompatibleProvider("https://example.invalid/chat/completions", "test-only", "model", 0, 12,
            thinking="enabled", reasoning_effort="high", max_attempts=1, request_timeout=180)
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"choices":[{"message":{"content":"by trivial"}}]}'
        with patch("provider.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = Response()
            provider.generate("test")
            payload = json.loads(factory.return_value.open.call_args.args[0].data)
            self.assertEqual(payload["thinking"], {"type": "enabled"})
            self.assertEqual(payload["reasoning_effort"], "high")
            self.assertNotIn("test-only", json.dumps(provider.metadata()))
        with patch("provider.urllib.request.build_opener") as factory:
            factory.return_value.open.side_effect = TimeoutError()
            with self.assertRaises(TimeoutError):
                provider.generate("test")
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_staging_excludes_build_results_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            for name in ("src/a.py", "src/__pycache__/x.pyc", "capsules/std/a/Capsule.lean",
                         "capsules/std/a/.lake/x.olean", "results/private.json", ".codex/auth.json"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test-only", encoding="utf-8")
            out = root / "out"
            self.assertEqual(stage(source, out), 2)
            self.assertFalse((out / "results").exists())
            self.assertFalse((out / ".codex").exists())
            self.assertFalse(list(out.rglob("*.olean")))
            with self.assertRaises(FileExistsError):
                stage(source, out)
