import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationConsistencyTest(unittest.TestCase):
    """防止公开文档与当前 API 和候选处理行为再次脱节。"""

    def test_security_policy_is_a_precompile_gate_not_an_agent_condition(self):
        document = (ROOT / "docs" / "security_policy.md").read_text(encoding="utf-8")
        manifest = json.loads(
            (ROOT / "benchmarks" / "security" / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertIn("不是证明实验条件", document)
        self.assertIn("reject_before_compile", document)
        self.assertIn("AxProverBase", document)
        self.assertIn("tracer-candidate-v2", document)
        self.assertTrue(manifest)
        self.assertTrue(all(case["id"].startswith("SP-") for case in manifest))
        self.assertTrue(all(case["type"] == "security_policy" for case in manifest))

    def test_part2_freezes_yxai_responses_and_reuses_ax_build_result(self):
        part2 = (ROOT / "docs" / "part2_capsule_feedback.md").read_text(encoding="utf-8")
        shared = (ROOT / "configs" / "axprover_yxai_gpt56_sol.yaml").read_text(encoding="utf-8")
        baseline = (ROOT / "configs" / "axprover_part1_experience.yaml").read_text(encoding="utf-8")
        capsule = (ROOT / "configs" / "axprover_part2_capsule.yaml").read_text(encoding="utf-8")
        self.assertIn("openai:gpt-5.6-sol", part2)
        self.assertIn("https://yxai.chat/v1", part2)
        self.assertIn("store=false", part2)
        self.assertIn("不运行 Lean、不调用模型", part2)
        self.assertIn("(build_success, message)", part2)
        self.assertIn("use_responses_api: true", shared)
        self.assertIn("store: false", shared)
        self.assertIn('effort: "high"', shared)
        self.assertIn("ExperienceProcessor", baseline)
        self.assertIn("MemorylessProcessor", capsule)

    def test_part12_handoff_records_successful_strict_pairing(self):
        handoff = json.loads(
            (ROOT / "results" / "handoff" / "part12-live-20260828" / "handoff.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(handoff["paired_problems"], 25)
        self.assertTrue(handoff["pairing_ok"])
        self.assertEqual(len(handoff["files"]), 5)

    def readmes(self):
        return {
            name: (ROOT / name).read_text(encoding="utf-8")
            for name in ("README.md", "README.zh-CN.md")
        }

    def test_readme_documents_deepseek_and_safe_key_prompt(self):
        confirmations = {
            "README.md": "only its length and last four characters",
            "README.zh-CN.md": "只显示字符数和末四位",
        }
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                self.assertIn("https://api.deepseek.com/chat/completions", readme)
                self.assertIn("--api-key-prompt", readme)
                self.assertIn(confirmations[name], readme)

    def test_readme_distinguishes_provider_and_compiler_failures(self):
        explanations = {
            "README.md": "compile_ok: false` alone does not mean the API is broken",
            "README.zh-CN.md": "compile_ok: false` 本身不代表 API 损坏",
        }
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                self.assertIn("provider_error", readme)
                self.assertIn(explanations[name], readme)

    def test_readmes_default_to_english_with_reciprocal_links(self):
        readmes = self.readmes()
        self.assertIn("**English** | [简体中文](README.zh-CN.md)", readmes["README.md"][:200])
        self.assertIn("[English](README.md) | **简体中文**", readmes["README.zh-CN.md"][:200])
        self.assertIn("## Quick start", readmes["README.md"])
        self.assertIn("## 快速开始", readmes["README.zh-CN.md"])
        for name, readme in readmes.items():
            with self.subTest(language=name):
                self.assertIn("](TRACER.png)", readme)
                self.assertIn("docs/RESEARCH_PROTOCOL.md", readme)
                self.assertIn("docs/RELATED_WORK.md", readme)
                self.assertIn("C_dynamic", readme)
                self.assertIn("C_failure", readme)
                for label in ("R-A", "R-B", "R-C", "R-D", "R-E", "R-F", "SP-1"):
                    self.assertIn(label, readme)

    def test_readme_commands_match_between_languages(self):
        # 仅比较执行命令；图中标签、目录注释和报错提示允许翻译。
        commands = []
        for name, readme in self.readmes().items():
            blocks = [match[1] for match in re.findall(r"^(```|~~~)[^\n]*\n(.*?)^\1", readme, re.MULTILINE | re.DOTALL)]
            with self.subTest(language=name):
                self.assertGreaterEqual(len(blocks), 18)
            commands.append([
                line for block in blocks for line in block.splitlines()
                if line.startswith(("python ", "lake ", "git ", "cd ", "$env:", "./scripts/", "bash "))
            ])
        self.assertTrue(commands[0])
        self.assertEqual(commands[0], commands[1])

    def test_readme_pilot_numbers_match_published_summary(self):
        expected = [
            ["18", "18/18(100.0%)", "18/18(100.0%)", "1.000", "1,750.4"],
            ["18", "16/18(88.9%)", "18/18(100.0%)", "1.111", "1,841.9"],
            ["18", "18/18(100.0%)", "18/18(100.0%)", "1.000", "2,906.1"],
        ]
        for name, readme in self.readmes().items():
            rows = []
            for line in readme.splitlines():
                if re.match(r"^\| [ABC][:：]", line):
                    cells = line.strip("|").split("|")[1:]
                    rows.append([
                        cell.replace("（", "(").replace("）", ")").replace(" ", "")
                        for cell in cells
                    ])
            with self.subTest(language=name):
                self.assertEqual(expected, rows)

    def test_readmes_share_evidence_links_and_repository_license(self):
        evidence = []
        for name, readme in self.readmes().items():
            links = set(re.findall(r"\]\((published/[^)]+)\)", readme))
            with self.subTest(language=name):
                self.assertEqual(6, len(links))
                self.assertIn("[MIT License](LICENSE)", readme)
                self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
            evidence.append(links)
        self.assertEqual(evidence[0], evidence[1])

    def test_methodology_documents_candidate_normalization(self):
        methodology = (ROOT / "docs" / "methodology.md").read_text(encoding="utf-8")
        schema = (ROOT / "docs" / "jsonl_schema.md").read_text(encoding="utf-8")
        self.assertIn("旧 SQLite 缓存", methodology)
        self.assertIn("`provider_error`", schema)


if __name__ == "__main__":
    unittest.main()
