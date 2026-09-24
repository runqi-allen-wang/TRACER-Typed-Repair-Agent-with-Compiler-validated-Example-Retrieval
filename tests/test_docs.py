import json
import re
import unittest
import xml.etree.ElementTree as ET
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
        self.assertEqual([case["id"] for case in manifest], [f"SP-{number}" for number in range(1, 13)])

    def test_feedback_and_security_status_links_match_both_readmes(self):
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                self.assertIn("docs/FEEDBACK_ADOPTION_V1.md", readme)
                self.assertIn("historical/README.md", readme)
                self.assertIn("docs/TRACER_REAL_V2.md", readme)
                self.assertIn("tracer_real_v2.enrollment.json", readme)
                self.assertIn("SP-1", readme)
                self.assertIn("SP-12", readme)

    def test_superseded_projects_are_indexed_outside_active_result_roots(self):
        archive = ROOT / "historical"
        self.assertTrue((archive / "README.md").is_file())
        self.assertTrue((archive / "evaluation18_pilot" / "README.md").is_file())
        self.assertTrue((archive / "feedback_study_v1" / "README.md").is_file())
        self.assertTrue((archive / "fate_m" / "README.md").is_file())
        self.assertEqual(
            {path.name for path in (ROOT / "published").iterdir() if path.is_dir()},
            {"research-six-arm-313f437f", "security-study-tracer-sp-v2"},
        )
        self.assertFalse((ROOT / "results" / "handoff").exists())
        self.assertTrue((archive / "fate_m" / "baseline" / "run_batch.py").is_file())

    def test_part2_freezes_yxai_responses_and_reuses_ax_build_result(self):
        root = ROOT / "historical" / "fate_m"
        part2 = (root / "docs" / "part2_capsule_feedback.md").read_text(encoding="utf-8")
        shared = (root / "configs" / "axprover_yxai_gpt56_sol.yaml").read_text(encoding="utf-8")
        baseline = (root / "configs" / "axprover_part1_experience.yaml").read_text(encoding="utf-8")
        capsule = (root / "configs" / "axprover_part2_capsule.yaml").read_text(encoding="utf-8")
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
            (
                ROOT
                / "historical"
                / "fate_m"
                / "results"
                / "handoff"
                / "part12-live-20260828"
                / "handoff.json"
            ).read_text(
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

    def test_readme_front_matter_separates_experiment_and_policy_namespaces(self):
        """README 首屏只解释当前研究臂和安全策略命名。"""
        headings = {
            "README.md": "## Experiment and policy namespaces",
            "README.zh-CN.md": "## 实验与安全命名体系",
        }
        quick_start = {
            "README.md": "## Quick start",
            "README.zh-CN.md": "## 快速开始",
        }
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                front = readme[: readme.index(quick_start[name])]
                self.assertIn(headings[name], front)
                for label in ("P-A", "P-B", "P-C"):
                    self.assertNotIn(label, front)
                for label in ("R-A", "R-B", "R-C", "R-D", "R-E", "R-F", "SP-1"):
                    self.assertIn(label, front)
                self.assertIn("C_dynamic", front)
                self.assertIn("C_failure", front)

    def test_readme_commands_match_between_languages(self):
        # 首页只保留核心运行场景；执行命令必须在两个语言版本中保持一致。
        commands = []
        for name, readme in self.readmes().items():
            blocks = [match[1] for match in re.findall(r"^(```|~~~)[^\n]*\n(.*?)^\1", readme, re.MULTILINE | re.DOTALL)]
            with self.subTest(language=name):
                self.assertGreaterEqual(len(blocks), 5)
            commands.append([
                line for block in blocks for line in block.splitlines()
                if line.startswith(("python ", "lake ", "git ", "cd ", "$env:", "./scripts/", "bash "))
            ])
        self.assertTrue(commands[0])
        self.assertEqual(commands[0], commands[1])

    def test_readme_latest_six_arm_numbers_match_published_summary(self):
        expected = [
            ["DeepSeekFlashv4.1", "R-A", "64/72(88.9%)", "69/72(95.8%)"],
            ["DeepSeekFlashv4.1", "R-B", "64/72(88.9%)", "69/72(95.8%)"],
            ["DeepSeekFlashv4.1", "R-C", "65/72(90.3%)", "69/72(95.8%)"],
            ["DeepSeekFlashv4.1", "R-D", "61/72(84.7%)", "68/72(94.4%)"],
            ["DeepSeekFlashv4.1", "R-E", "66/72(91.7%)", "70/72(97.2%)"],
            ["DeepSeekFlashv4.1", "R-F", "64/72(88.9%)", "70/72(97.2%)"],
            ["DeepSeekPro0813", "R-A", "61/72(84.7%)", "67/72(93.1%)"],
            ["DeepSeekPro0813", "R-B", "56/72(77.8%)", "65/72(90.3%)"],
            ["DeepSeekPro0813", "R-C", "60/72(83.3%)", "67/72(93.1%)"],
            ["DeepSeekPro0813", "R-D", "56/72(77.8%)", "65/72(90.3%)"],
            ["DeepSeekPro0813", "R-E", "61/72(84.7%)", "67/72(93.1%)"],
            ["DeepSeekPro0813", "R-F", "57/72(79.2%)", "65/72(90.3%)"],
        ]
        for name, readme in self.readmes().items():
            rows = []
            for line in readme.splitlines():
                if line.startswith("| DeepSeek "):
                    cells = line.strip("|").split("|")
                    normalized = [
                        cell.replace("（", "(")
                        .replace("）", ")")
                        .replace("**", "")
                        .replace(" ", "")
                        for cell in cells
                    ]
                    rows.append([normalized[0], normalized[1], normalized[3], normalized[4]])
            with self.subTest(language=name):
                self.assertEqual(expected, rows)
                self.assertNotIn("## Pilot results", readme)
                self.assertNotIn("## 实验结果", readme)

    def test_readme_chart_matches_published_six_arm_summary(self):
        relative = "docs/assets/repair24-six-arm-results.svg"
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                self.assertIn(f"]({relative})", readme)
        summary = json.loads(
            (ROOT / "published" / "research-six-arm-313f437f" / "summary.json").read_text(
                encoding="utf-8"
            )
        )
        root = ET.parse(ROOT / relative).getroot()
        bars = {
            (node.attrib["data-model"], node.attrib["data-arm"], node.attrib["data-stage"]): float(
                node.attrib["data-value"]
            )
            for node in root.findall("{http://www.w3.org/2000/svg}rect")
            if "data-stage" in node.attrib
        }
        self.assertEqual(24, len(bars))
        for row in summary["summary"]:
            key = (row["model"], row["arm"])
            self.assertAlmostEqual(bars[(*key, "first")], 100 * row["first"] / row["tasks"], places=5)
            self.assertAlmostEqual(
                bars[(*key, "within_3")], 100 * row["success"] / row["tasks"], places=5
            )

    def test_readme_tracer_real_v2_counts_match_public_screening_ledgers(self):
        reports = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(
                (ROOT / "benchmarks" / "real_repairs" / "tracer_real_v2_screening").glob(
                    "*.screen.json"
                )
            )
        ]
        totals = {
            "projects": len(reports),
            "candidates": sum(row["candidates"] for row in reports),
            "accepted": sum(row["accepted"] for row in reports),
            "rejected": sum(row["rejected"] for row in reports),
        }
        self.assertGreaterEqual(totals["projects"], 5)
        self.assertEqual(totals["candidates"], totals["accepted"] + totals["rejected"])
        expected = {
            "README.md": [
                f'{totals["candidates"]:,}',
                f'{totals["accepted"]:,} admitted',
                f'{totals["rejected"]:,} rejected',
            ],
            "README.zh-CN.md": [
                f'{totals["candidates"]:,}',
                f'{totals["accepted"]:,} 个纳入',
                f'{totals["rejected"]:,} 个拒绝',
            ],
        }
        remaining = 1576 - totals["candidates"]
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                for fragment in expected[name]:
                    self.assertIn(fragment, readme)
                if remaining:
                    self.assertIn(str(remaining), readme)
        project_words = {5: "Five", 6: "Six"}
        english_phrase = (
            f'{project_words[totals["projects"]]} projects fully screened'
            if remaining else 'Six projects fully screened'
        )
        self.assertIn(
            english_phrase,
            (ROOT / "README.md").read_text(encoding="utf-8"),
        )
        self.assertIn(
            "五个项目完成全量筛查" if remaining else "六个项目全部筛查",
            (ROOT / "README.zh-CN.md").read_text(encoding="utf-8"),
        )
        if not remaining:
            for readme in self.readmes().values():
                self.assertIn("35%", readme)
                self.assertIn("40%", readme)

    def test_readmes_do_not_promote_superseded_smoke_pilot(self):
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                self.assertNotIn("P-A / P-B / P-C", readme)
                self.assertNotIn("published/pilot-20260826T122354Z-d628742d", readme)

    def test_readmes_share_evidence_links_and_repository_license(self):
        evidence = []
        for name, readme in self.readmes().items():
            links = set(re.findall(r"\]\((published/[^)]+)\)", readme))
            with self.subTest(language=name):
                self.assertEqual(2, len(links))
                self.assertIn("published/research-six-arm-313f437f", links)
                self.assertIn("published/security-study-tracer-sp-v2", links)
                self.assertIn("[MIT License](LICENSE)", readme)
                self.assertIn("MIT License", (ROOT / "LICENSE").read_text(encoding="utf-8"))
            evidence.append(links)
        self.assertEqual(evidence[0], evidence[1])

    def test_evidence_register_separates_results_from_plans(self):
        progress = (ROOT / "PROGRESS.md").read_text(encoding="utf-8")
        for heading in (
            "## 已发布证据",
            "## 可复验实现，但尚未完成研究验收",
            "## 仅有历史说明、当前仓库不能独立核验",
            "## 下一阶段",
        ):
            self.assertIn(heading, progress)
        self.assertNotIn("当前 `leiteng`", progress)
        self.assertIn("重复与实验臂不能扩充为 864 道独立样本", progress)
        self.assertIn("不作为发布结果", progress)
        for name, readme in self.readmes().items():
            with self.subTest(language=name):
                self.assertIn("[PROGRESS.md](PROGRESS.md)", readme)

    def test_methodology_documents_candidate_normalization(self):
        methodology = (ROOT / "docs" / "methodology.md").read_text(encoding="utf-8")
        schema = (ROOT / "docs" / "jsonl_schema.md").read_text(encoding="utf-8")
        self.assertIn("旧 SQLite 缓存", methodology)
        self.assertIn("`provider_error`", schema)


if __name__ == "__main__":
    unittest.main()
