import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationConsistencyTest(unittest.TestCase):
    """防止公开文档与当前 API 和候选处理行为再次脱节。"""

    def test_readme_documents_deepseek_and_safe_key_prompt(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("https://api.deepseek.com/chat/completions", readme)
        self.assertIn("--api-key-prompt", readme)
        self.assertIn("不显示长度、末四位或任何密钥字符", readme)
        self.assertIn("同源重定向", readme)
        self.assertIn("run_tac", readme)

    def test_readme_distinguishes_provider_and_compiler_failures(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("provider_error", readme)
        self.assertIn("compile_ok: false` 本身不代表 API 损坏", readme)

    def test_part2_freezes_deepseek_flash_and_reuses_ax_build_result(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        part2 = (ROOT / "docs" / "part2_capsule_feedback.md").read_text(encoding="utf-8")
        for document in (readme, part2):
            self.assertIn("openai:deepseek-v4-flash", document)
            self.assertIn("https://api.deepseek.com", document)
        self.assertIn("不运行 Lean、不调用模型", part2)
        self.assertIn("(build_success, message)", part2)

    def test_methodology_documents_candidate_normalization(self):
        methodology = (ROOT / "docs" / "methodology.md").read_text(encoding="utf-8")
        schema = (ROOT / "docs" / "jsonl_schema.md").read_text(encoding="utf-8")
        self.assertIn("旧 SQLite 缓存", methodology)
        self.assertIn("`provider_error`", schema)

    def test_readme_builds_before_running_end_to_end_tests(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quick_start = readme.split("## 快速开始", 1)[1].split("## 公开失败 gallery", 1)[0]
        self.assertLess(quick_start.index("lake build"), quick_start.index("unittest discover"))

    def test_readme_pack_example_does_not_overwrite_the_public_gallery(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pack_example = readme.split("生成一个本地 capsule", 1)[1].split("回放该本地工件", 1)[0]
        self.assertNotIn("capsules/std/unknown-identifier", pack_example)
        self.assertIn("results/work/unknown-identifier", pack_example)

    def test_formal_pilot_documents_environment_and_review_gate(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        results = (ROOT / "results" / "README.md").read_text(encoding="utf-8")
        for name in (
            "LEAN_PROOF_API_URL",
            "LEAN_PROOF_API_KEY",
            "LEAN_PROOF_MODEL",
            "LEAN_PROOF_TEMPERATURE",
            "LEAN_PROOF_MAX_TOKENS",
        ):
            self.assertIn(name, readme)
        self.assertIn("--require-manual-review", readme)
        self.assertIn("export_pilot.py", results)
        self.assertIn("git add -f", results)


if __name__ == "__main__":
    unittest.main()
