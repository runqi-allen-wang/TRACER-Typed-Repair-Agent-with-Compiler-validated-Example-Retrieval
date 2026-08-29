"""最新版主线与研究补丁的兼容回归；不联网，不生成真实模型数据。"""
import ast
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

from agent import solve_problem
from provider import generation_finish_reason, parse_generation
from research import load_config, run_matrix, valid_protocol_record
from scripts import export_pilot
from leancapsule.ax_integration import CapsuleFeedbackSessions
from leancapsule.feedback import CapsuleFeedback, normalized_feedback_text
from leancapsule.pairing import validate_paired_runs


class MergeCompatibilityTest(unittest.TestCase):
    def test_responses_truncation_preserves_usage_and_rejects_partial_code(self):
        for content in (None, "by trivial"):
            body = {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [], "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}
            if content is not None:
                body["output_text"] = content
            generation = parse_generation(json.dumps(body), "test_only")
            class FakeProvider:
                name = "test_only"

                def generate(self, prompt):
                    return generation

            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source = root / "task.lean"
                source.write_text("import Std\ntheorem target : True := sorry\n", encoding="utf-8")
                with patch("agent.compile_candidate") as compiler:
                    record = solve_problem(source, "target", "B", FakeProvider(), 1, 60,
                        ROOT / "examples", root / "cache", root / "solutions", root / "runs.jsonl", use_cache=False)
                compiler.assert_not_called()
                self.assertEqual(record["diagnostic"]["category"], "generation_truncated")
                self.assertEqual(record["usage"]["total_tokens"], 30)
                self.assertTrue(valid_protocol_record(record))

    def test_responses_finished_and_unfinished_states_are_distinct(self):
        self.assertEqual(generation_finish_reason({"status": "completed"}), "stop")
        for status in ("failed", "cancelled", "in_progress", "queued", "incomplete"):
            self.assertEqual(generation_finish_reason({"status": status}), "incomplete")
        self.assertEqual(parse_generation('{"output_text":null}', "test").candidate, "")

    def test_research_provider_does_not_inherit_protocol_or_reasoning(self):
        config = load_config(ROOT / "experiments/research.example.json")
        config = copy.deepcopy(config)
        for model in config["models"]:
            model["model"] = "test-only"
            model.pop("reasoning_effort", None)
        keys = {m["api_key_env"]: "non-secret-test-value" for m in config["models"]}
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"LEAN_PROOF_WIRE_API": "responses", "LEAN_PROOF_REASONING_EFFORT": "medium"}), \
             patch("research.OpenAICompatibleProvider") as factory, \
             patch("research.check_benchmark", side_effect=RuntimeError("停止于网络调用前")):
            with self.assertRaisesRegex(RuntimeError, "停止于网络调用前"):
                run_matrix(config, ROOT / "benchmarks/repair24/manifest.json", Path(directory) / "run", api_keys=keys)
            self.assertEqual(factory.call_count, len(config["models"]))
            for call in factory.call_args_list:
                self.assertEqual(call.kwargs["wire_api"], "chat_completions")
                self.assertIsNone(call.kwargs["reasoning_effort"])
                self.assertEqual(call.kwargs["max_attempts"], 1)

    def test_feedback_text_preserves_distinctions_after_common_prefix(self):
        prefix = "unknown identifier " + "x" * 100
        left = normalized_feedback_text("unknown_identifier", prefix + " first")
        right = normalized_feedback_text("unknown_identifier", prefix + " second")
        self.assertNotEqual(left, right)
        self.assertIn("first", json.loads(left)["diagnostic"])
        session = CapsuleFeedback()
        session.observe(compile_ok=False, diagnostic_text=prefix + " first")
        restored = CapsuleFeedback(state=session.export_state())
        self.assertEqual(restored.observe(compile_ok=False, diagnostic_text=prefix + " first")["repeat_count"], 2)
        self.assertEqual(restored.observe(compile_ok=False, diagnostic_text=prefix + " second")["repeat_count"], 1)

    def test_random_session_filename_restores_exact_theorem(self):
        with tempfile.TemporaryDirectory() as directory:
            pool = CapsuleFeedbackSessions(state_dir=directory)
            pool.observe("Demo.lean:甲.target", (False, "error: unknown identifier `x`"), round_no=1)
            pool.observe("Demo.lean:乙.target", (False, "error: unknown identifier `x`"), round_no=1)
            files = list(Path(directory).glob("session-*.json"))
            self.assertEqual(len(files), 2)
            keys = {json.loads(p.read_text(encoding="utf-8"))["theorem_key"] for p in files}
            self.assertEqual(keys, {"Demo.lean:甲.target", "Demo.lean:乙.target"})
            restored = CapsuleFeedbackSessions(state_dir=directory)
            self.assertEqual(restored.observe("Demo.lean:甲.target", (False, "error: unknown identifier `x`"), round_no=2)["repeat_count"], 2)

    def test_corrected_upstream_pairing_uses_exact_proposals(self):
        root = ROOT / "results/handoff/part12-live-20260828-corrected"
        read = lambda name: [json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines() if line.strip()]
        left, right = read("baseline-full.jsonl"), read("capsule-full.jsonl")
        result = validate_paired_runs(left, right)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["pair_count"], 25)
        self.assertTrue(all(p["first_round_candidate_equal"] and p["first_round_proposal_equal"] for p in result["pairs"]))
        changed = copy.deepcopy(right)
        changed[0]["first_round_candidate"] += "\n-- changed"
        self.assertFalse(validate_paired_runs(left, changed)["ok"])

    def test_handoff_has_readable_metadata_without_derived_fields(self):
        prohibited_field_parts = ("sha" + "256", "finger" + "print")

        def check(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertFalse(any(word in key.lower() for word in prohibited_field_parts), key)
                    check(child)
            elif isinstance(value, list):
                for child in value:
                    check(child)
        for directory in (ROOT / "results/handoff").glob("part12-live-*"):
            manifest = json.loads((directory / "handoff.json").read_text(encoding="utf-8"))
            check(manifest)
            for entry in manifest["files"]:
                path = directory / entry["path"]
                # 清单记录 LF 交接文本大小；Windows checkout 的 CRLF 不改变含义。
                self.assertEqual(len(path.read_text(encoding="utf-8").encode("utf-8")), entry["bytes"])
                if path.suffix == ".jsonl":
                    for line in path.read_text(encoding="utf-8").splitlines():
                        check(json.loads(line))
                else:
                    check(json.loads(path.read_text(encoding="utf-8")))

    def test_runtime_and_experiment_scripts_do_not_import_digest_library(self):
        prohibited_module = "ha" + "sh" + "lib"
        for folder in (ROOT / "src", ROOT / "baseline", ROOT / "scripts"):
            for path in folder.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        self.assertNotIn(prohibited_module, [alias.name for alias in node.names], str(path))
                    elif isinstance(node, ast.ImportFrom):
                        self.assertNotEqual(node.module, prohibited_module, str(path))

    def test_feasibility_results_contain_only_readable_comparison_metadata(self):
        prohibited_field_parts = ("sha" + "256", "finger" + "print")
        for path in (
            ROOT / "results/capsule_feasibility/summary.json",
            ROOT / "results/capsule_challenges/summary.json",
        ):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for case in payload["cases"] if "cases" in payload else [*payload["core_cases"], *payload["challenge_cases"]]:
                self.assertFalse(
                    any(part in key.lower() for key in case for part in prohibited_field_parts),
                    f"{path}: {case['case_id']}",
                )
                self.assertEqual(case["strict_comparison_method"], "direct_normalized_text_equality")

    def test_repository_text_does_not_reintroduce_prohibited_derived_identifiers(self):
        # PowerShell 的 hashtable 是普通容器，不属于被禁止的派生摘要机制。
        prohibited = ("sha" + "256", "ha" + "sh" + "lib", "finger" + "print")
        suffixes = {".py", ".json", ".jsonl", ".md", ".toml", ".yaml", ".yml", ".ps1", ".sh", ".csv", ".txt"}
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if ".lake" in path.parts or path.name == "lake-manifest.json":
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace").lower()
            self.assertFalse(any(term in text for term in prohibited), str(path))

    def test_export_from_source_archive_does_not_inherit_parent_git_metadata(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(export_pilot, "ROOT", Path(directory)), \
             patch.object(export_pilot.subprocess, "run") as run:
            value = export_pilot.git_revision()
        run.assert_not_called()
        self.assertEqual(value, "unavailable (source export without repository metadata)")
