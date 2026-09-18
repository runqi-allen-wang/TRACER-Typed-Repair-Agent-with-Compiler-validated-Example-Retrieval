import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from adaptive_router import route_feedback  # noqa: E402
from compiler_feedback import build_feedback_record  # noqa: E402
from error_state_graph import build_error_state_graph, validate_error_state_graph  # noqa: E402


class ErrorStateGraphTest(unittest.TestCase):
    def graph(self, round_no=1):
        record = build_feedback_record(
            case_id="demo",
            diagnostic_text="Demo.lean:3:7: error: unknown identifier 'missingName'",
            compile_ok=False,
            returncode=1,
            round_no=round_no,
        )
        return build_error_state_graph(
            record,
            theorem_name="Demo.target",
            source_text="import Std\nnamespace Demo\ntheorem target : True := by trivial\nend Demo\n",
            candidate="by exact missingName",
        )

    def test_every_signal_has_raw_evidence_edge(self):
        graph = self.graph()
        validate_error_state_graph(graph)
        signals = {node["id"] for node in graph["nodes"] if node["type"] == "diagnostic_signal"}
        supported = {edge["source"] for edge in graph["edges"] if edge["relation"] == "supported_by"}
        self.assertEqual(signals, supported)
        spans = [node for node in graph["nodes"] if node["type"] == "source_span"]
        self.assertEqual(spans[0]["line"], 3)
        self.assertIn("theorem target", spans[0]["text"])

    def test_transition_and_adaptive_escalation_are_explicit(self):
        first = self.graph(1)
        record = build_feedback_record(
            case_id="demo",
            diagnostic_text="Demo.lean:3:7: error: unknown identifier 'otherMissing'",
            compile_ok=False,
            returncode=1,
            round_no=2,
        )
        second = build_error_state_graph(
            record,
            theorem_name="Demo.target",
            source_text="import Std\nnamespace Demo\ntheorem target : True := by trivial\nend Demo\n",
            candidate="by exact otherMissing",
            previous_graph=first,
        )
        self.assertFalse(second["transition"]["category_changed"])
        route = route_feedback(second, previous_graphs=[first])
        self.assertEqual(route["representation"], "raw_plus_structured")
        self.assertEqual(route["retrieval_strategy"], "diagnostic")
        self.assertEqual(route["method_status"], "deterministic_prototype_not_learned")

    def test_infrastructure_event_stops_router(self):
        record = build_feedback_record(
            case_id="provider",
            diagnostic_text="provider service unavailable",
            compile_ok=False,
            returncode=None,
            origin="provider",
            category_hint="provider_error",
        )
        graph = build_error_state_graph(
            record, theorem_name="Demo.target", source_text="", candidate="",
        )
        route = route_feedback(graph)
        self.assertEqual(route["action"], "stop_infrastructure")
        self.assertEqual(route["retrieval_strategy"], "none")


if __name__ == "__main__":
    unittest.main()
