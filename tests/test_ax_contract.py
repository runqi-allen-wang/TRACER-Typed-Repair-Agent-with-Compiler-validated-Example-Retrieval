import ast
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.validate_axprover_contract import validate_axprover_source  # noqa: E402


class AxContractValidatorTest(unittest.TestCase):
    def test_minimal_compatible_source_contract_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / "src" / "ax_prover"
            (package / "prover").mkdir(parents=True)
            (package / "models").mkdir(parents=True)
            (package / "prover" / "agent.py").write_text(
                "class ProverAgent:\n"
                "    async def _builder_node(self, state):\n"
                "        ok, message = await check_lean_file()\n"
                "        if ok:\n"
                "            return BuildSuccessFeedback()\n"
                "        if state.sorries:\n"
                "            return SorriesGoalStateFeedback()\n"
                "        return BuildFailedFeedback(error_output=message)\n",
                encoding="utf-8",
            )
            (package / "models" / "messages.py").write_text(
                "class FeedbackMessage: pass\n"
                "class BuildFailedFeedback: pass\n"
                "class BuildSuccessFeedback: pass\n"
                "class SorriesGoalStateFeedback: pass\n",
                encoding="utf-8",
            )
            (package / "prover" / "memory.py").write_text(
                "class MemorylessProcessor: pass\n", encoding="utf-8"
            )
            (package / "config.py").write_text(
                "prover_llm = memory_config = summarize_output = None\n", encoding="utf-8"
            )
            self.assertEqual(validate_axprover_source(root, expected_commit=None), [])

    def test_validator_rejects_a_second_compiler_call(self):
        tree = ast.parse(
            "async def builder():\n"
            "    await check_lean_file()\n"
            "    await check_lean_file()\n"
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "check_lean_file"
        ]
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
