"""离线分析候选是否响应编译反馈，以及动态检索是否实际变化。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from compiler_feedback import FeedbackProtocolError, build_feedback_record


PROTOCOL_VERSION = "tracer-feedback-adoption-v1"
INFRASTRUCTURE_CATEGORIES = {
    "provider_error",
    "compiler_unavailable",
    "timeout",
    "patch_error",
    "candidate_security",
}
TOKEN_RE = re.compile(r"[^\W\d][\w']*", re.UNICODE)


def _tokens(text: object) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(str(text or ""))}


def _top_paths(row: dict[str, Any]) -> list[str]:
    examples = row.get("retrieved_examples")
    if not isinstance(examples, list):
        return []
    return [str(item.get("path", "")) for item in examples if isinstance(item, dict)]


def _feedback_record(row: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    category = str(row.get("diagnostic", {}).get("category") or "")
    if category in INFRASTRUCTURE_CATEGORIES:
        return None, "infrastructure"
    raw = str(row.get("raw_diagnostics") or "")
    if not raw.strip():
        return None, "empty"
    try:
        return build_feedback_record(
            case_id=str(row.get("problem_id") or "unknown"),
            diagnostic_text=raw,
            compile_ok=bool(row.get("compile_ok")),
            returncode=row.get("compile_returncode"),
            timed_out=bool(row.get("compile_timed_out")),
            round_no=int(row.get("round") or 1),
        ), "available"
    except (FeedbackProtocolError, TypeError, ValueError):
        return None, "conversion_error"


def _touches_relevant_signal(previous: str, current: str, record: dict[str, Any]) -> bool | None:
    """判断候选改动是否触及上一轮诊断中的可审计信号。"""

    before, after = _tokens(previous), _tokens(current)
    changed = before ^ after
    signal_tokens: set[str] = set()
    unknown_values: set[str] = set()
    expected_values: set[str] = set()
    for signal in record["structured"]["signals"]:
        value_tokens = _tokens(signal.get("value"))
        signal_tokens.update(value_tokens)
        if signal.get("kind") == "unknown_identifier":
            unknown_values.update(value_tokens)
        if signal.get("kind") == "expected_type":
            expected_values.update(value_tokens)
    if not signal_tokens:
        return None
    if unknown_values & before and not unknown_values & after:
        return True
    if expected_values & (after - before):
        return True
    return bool(changed & signal_tokens)


def analyze_trace(rows: list[dict[str, Any]], source: str = "") -> dict[str, Any]:
    """分析单个任务的逐轮 JSONL；不推断模型的内部意图。"""

    if not rows:
        raise ValueError("轨迹不能为空")
    ordered = sorted(rows, key=lambda row: int(row.get("round") or 0))
    rounds = [int(row.get("round") or 0) for row in ordered]
    if rounds != list(range(1, len(ordered) + 1)):
        raise ValueError("轨迹轮次必须从 1 连续递增")
    run_ids = {str(row.get("run_id") or "") for row in ordered}
    if len(run_ids) != 1 or "" in run_ids:
        raise ValueError("单条轨迹必须且只能包含一个非空 run_id")

    transitions: list[dict[str, Any]] = []
    for previous, current in zip(ordered, ordered[1:]):
        feedback, status = _feedback_record(previous)
        previous_candidate = str(previous.get("candidate") or "")
        current_candidate = str(current.get("candidate") or "")
        changed = previous_candidate != current_candidate
        relevant = _touches_relevant_signal(previous_candidate, current_candidate, feedback) if feedback else None
        if current.get("cache_hit"):
            adoption = "cache_reuse"
        elif status != "available":
            adoption = status
        elif not changed:
            adoption = "candidate_unchanged"
        elif relevant is True:
            adoption = "relevant_change"
        elif relevant is False:
            adoption = "changed_without_signal_match"
        else:
            adoption = "changed_unassessable"

        previous_paths, current_paths = _top_paths(previous), _top_paths(current)
        query_changed = str(previous.get("retrieval_query") or "") != str(current.get("retrieval_query") or "")
        transitions.append(
            {
                "from_round": previous["round"],
                "to_round": current["round"],
                "from_category": previous.get("diagnostic", {}).get("category", "unclassified"),
                "to_category": current.get("diagnostic", {}).get("category", "unclassified"),
                "feedback_conversion": status,
                "feedback_delivery": "recorded" if current.get("feedback_payload") else "not_recorded",
                "candidate_changed": changed,
                "relevant_signal_touched": relevant,
                "adoption_observation": adoption,
                "cache_reuse": bool(current.get("cache_hit")),
                "retrieval_strategy": current.get("retrieval_strategy"),
                "query_changed": query_changed,
                "top_k_changed": previous_paths != current_paths,
                "previous_top_k": previous_paths,
                "current_top_k": current_paths,
            }
        )

    return {
        "protocol_version": PROTOCOL_VERSION,
        "source": source,
        "run_id": next(iter(run_ids)),
        "experiment_id": ordered[0].get("experiment_id"),
        "problem_id": ordered[0].get("problem_id"),
        "condition": ordered[0].get("condition"),
        "retrieval_strategy": ordered[0].get("retrieval_strategy"),
        "feedback_representation": ordered[0].get("feedback_representation", "legacy-unrecorded"),
        "rounds": len(ordered),
        "final_compile_ok": bool(ordered[-1].get("compile_ok")),
        "transitions": transitions,
    }


def summarize_analyses(analyses: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(analyses)
    transitions = [transition for item in items for transition in item["transitions"]]
    adoption = Counter(item["adoption_observation"] for item in transitions)
    dynamic = [item for item in transitions if item.get("retrieval_strategy") == "diagnostic"]
    static = [item for item in transitions if item.get("retrieval_strategy") == "static"]
    assessable = [item for item in transitions if item["adoption_observation"] in {
        "relevant_change", "changed_without_signal_match", "candidate_unchanged"
    }]
    return {
        "protocol_version": PROTOCOL_VERSION,
        "traces": len(items),
        "round_transitions": len(transitions),
        "feedback_adoption_observations": dict(sorted(adoption.items())),
        "relevant_change_rate": (
            sum(item["adoption_observation"] == "relevant_change" for item in assessable) / len(assessable)
            if assessable else None
        ),
        "repeated_error_category_rate": (
            sum(item["from_category"] == item["to_category"] for item in transitions) / len(transitions)
            if transitions else None
        ),
        "dynamic_retrieval": {
            "transitions": len(dynamic),
            "query_change_rate": sum(item["query_changed"] for item in dynamic) / len(dynamic) if dynamic else None,
            "top_k_change_rate": sum(item["top_k_changed"] for item in dynamic) / len(dynamic) if dynamic else None,
        },
        "static_retrieval": {
            "transitions": len(static),
            "query_change_rate": sum(item["query_changed"] for item in static) / len(static) if static else None,
            "top_k_change_rate": sum(item["top_k_changed"] for item in static) / len(static) if static else None,
        },
        "interpretation": (
            "候选和检索变化是可观察行为，不等同于模型内部因果采纳；"
            "正式结论仍需冻结的 raw/normalized/structured 配对实验。"
        ),
    }


def load_trace_files(paths: Iterable[Path]) -> list[dict[str, Any]]:
    analyses: list[dict[str, Any]] = []
    for supplied in paths:
        path = supplied.resolve()
        files = sorted(path.rglob("runs.jsonl")) if path.is_dir() else [path]
        for file in files:
            rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
            analyses.append(analyze_trace(rows, str(file)))
    return analyses


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="runs.jsonl 文件或包含它们的研究目录")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        analyses = load_trace_files(args.paths)
        result = {"summary": summarize_analyses(analyses), "traces": analyses}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
