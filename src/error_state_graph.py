"""将 Compiler Feedback v1 转换为可审计的错误状态图。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from compiler_feedback import validate_feedback_record


PROTOCOL_VERSION = "tracer-error-state-graph-v1"
LOCATION_RE = re.compile(r"(?m)^(?P<path>.+?):(?P<line>\d+):(?P<column>\d+):")


class ErrorStateGraphError(ValueError):
    """错误状态图不符合冻结协议。"""


def _excerpt(value: object, limit: int = 2400) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _source_window(source: str, line: int, radius: int = 1) -> dict[str, Any]:
    lines = source.splitlines()
    if line < 1 or line > len(lines):
        return {"start_line": line, "end_line": line, "text": ""}
    start = max(1, line - radius)
    end = min(len(lines), line + radius)
    return {
        "start_line": start,
        "end_line": end,
        "text": "\n".join(lines[start - 1:end]),
    }


def _signal_values(graph: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted(
        (str(node.get("kind")), str(node.get("value")))
        for node in graph.get("nodes", [])
        if node.get("type") == "diagnostic_signal"
    )


def build_error_state_graph(
    feedback_record: dict[str, Any],
    *,
    theorem_name: str,
    source_text: str,
    candidate: str,
    previous_graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造一轮错误状态图，每个提取信号仍指向原始诊断证据。"""

    validate_feedback_record(feedback_record)
    if not theorem_name.strip():
        raise ErrorStateGraphError("theorem_name 不能为空")
    if previous_graph is not None:
        validate_error_state_graph(previous_graph)

    round_no = int(feedback_record["round"])
    category = str(feedback_record["structured"]["category"])
    state_id = f"state:{round_no}"
    theorem_id = "theorem:target"
    error_id = f"error:{round_no}"
    candidate_id = f"candidate:{round_no}"
    raw_id = f"raw:{round_no}"
    nodes: list[dict[str, Any]] = [
        {"id": state_id, "type": "error_state", "round": round_no, "category": category},
        {"id": theorem_id, "type": "theorem", "name": theorem_name},
        {"id": candidate_id, "type": "candidate", "text": _excerpt(candidate, 6000)},
        {
            "id": error_id,
            "type": "diagnostic",
            "category": category,
            "summary": _excerpt(feedback_record["normalized"].get("summary")),
            "evidence_excerpt": feedback_record["structured"]["category_evidence"],
        },
        {
            "id": raw_id,
            "type": "raw_diagnostic",
            "text": feedback_record["raw"]["text"],
        },
    ]
    edges: list[dict[str, str]] = [
        {"source": state_id, "relation": "targets", "target": theorem_id},
        {"source": state_id, "relation": "observed_after", "target": candidate_id},
        {"source": state_id, "relation": "has_diagnostic", "target": error_id},
        {"source": error_id, "relation": "reported_in", "target": raw_id},
    ]

    match = LOCATION_RE.search(feedback_record["raw"]["text"])
    if match:
        line, column = int(match.group("line")), int(match.group("column"))
        location_id = f"source_span:{round_no}"
        nodes.append({
            "id": location_id,
            "type": "source_span",
            "line": line,
            "column": column,
            **_source_window(source_text, line),
        })
        edges.append({"source": error_id, "relation": "located_at", "target": location_id})

    for index, signal in enumerate(feedback_record["structured"]["signals"], 1):
        signal_id = f"signal:{round_no}:{index}"
        evidence_id = f"evidence:{round_no}:{index}"
        nodes.extend([
            {
                "id": signal_id,
                "type": "diagnostic_signal",
                "kind": signal["kind"],
                "value": signal["value"],
            },
            {
                "id": evidence_id,
                "type": "raw_evidence",
                "text": signal["evidence_excerpt"],
            },
        ])
        edges.extend([
            {"source": error_id, "relation": "exposes", "target": signal_id},
            {"source": signal_id, "relation": "supported_by", "target": evidence_id},
        ])

    previous_category = None
    transition = None
    if previous_graph is not None:
        previous_category = str(previous_graph["current_state"]["category"])
        before = set(_signal_values(previous_graph))
        after = {(node["kind"], node["value"]) for node in nodes if node.get("type") == "diagnostic_signal"}
        transition = {
            "from_round": previous_graph["current_state"]["round"],
            "to_round": round_no,
            "from_category": previous_category,
            "to_category": category,
            "category_changed": previous_category != category,
            "resolved": category == "ok",
            "added_signals": [list(item) for item in sorted(after - before)],
            "removed_signals": [list(item) for item in sorted(before - after)],
        }

    graph = {
        "schema_version": PROTOCOL_VERSION,
        "case_id": feedback_record["case_id"],
        "current_state": {"id": state_id, "round": round_no, "category": category},
        "nodes": nodes,
        "edges": edges,
        "transition": transition,
        "evidence_policy": "每个诊断类别与信号必须保留可在 Compiler Feedback v1 原始层定位的片段。",
    }
    validate_error_state_graph(graph)
    return graph


def validate_error_state_graph(graph: dict[str, Any]) -> None:
    if graph.get("schema_version") != PROTOCOL_VERSION:
        raise ErrorStateGraphError("错误状态图版本不匹配")
    state = graph.get("current_state")
    nodes, edges = graph.get("nodes"), graph.get("edges")
    if not isinstance(state, dict) or not isinstance(nodes, list) or not isinstance(edges, list):
        raise ErrorStateGraphError("错误状态图缺少 state、nodes 或 edges")
    ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(ids) != len(nodes) or any(not isinstance(value, str) or not value for value in ids):
        raise ErrorStateGraphError("节点 ID 非法")
    if len(ids) != len(set(ids)):
        raise ErrorStateGraphError("节点 ID 重复")
    if state.get("id") not in ids or type(state.get("round")) is not int:
        raise ErrorStateGraphError("current_state 未指向有效节点")
    for edge in edges:
        if set(edge) != {"source", "relation", "target"}:
            raise ErrorStateGraphError("边字段非法")
        if edge["source"] not in ids or edge["target"] not in ids or not edge["relation"]:
            raise ErrorStateGraphError("边引用不存在的节点")
    evidence_ids = {
        edge["source"]
        for edge in edges
        if edge["relation"] == "supported_by"
        and any(node.get("id") == edge["target"] and node.get("type") == "raw_evidence" for node in nodes)
    }
    signal_ids = {node["id"] for node in nodes if node.get("type") == "diagnostic_signal"}
    if signal_ids - evidence_ids:
        raise ErrorStateGraphError("结构化信号缺少原始证据边")


def write_graph(path: Path, graph: dict[str, Any]) -> None:
    validate_error_state_graph(graph)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
