"""基于错误状态图的确定性反馈路由器原型。"""

from __future__ import annotations

import json
from typing import Any

from error_state_graph import validate_error_state_graph


PROTOCOL_VERSION = "tracer-adaptive-router-v1"
INFRASTRUCTURE = {"timeout", "provider_error", "compiler_unavailable"}


def _nodes(graph: dict[str, Any], node_type: str) -> list[dict[str, Any]]:
    return [node for node in graph["nodes"] if node.get("type") == node_type]


def _structured_payload(graph: dict[str, Any]) -> str:
    diagnostic = _nodes(graph, "diagnostic")[0]
    signals = [
        {"kind": node["kind"], "value": node["value"]}
        for node in _nodes(graph, "diagnostic_signal")
    ]
    locations = [
        {key: node.get(key) for key in ("line", "column", "start_line", "end_line", "text")}
        for node in _nodes(graph, "source_span")
    ]
    return json.dumps(
        {"category": diagnostic["category"], "signals": signals, "source_spans": locations},
        ensure_ascii=False,
        sort_keys=True,
    )


def _raw_payload(graph: dict[str, Any]) -> str:
    complete = _nodes(graph, "raw_diagnostic")
    if complete:
        return complete[0]["text"]
    evidence = [node["text"] for node in _nodes(graph, "raw_evidence")]
    diagnostic = _nodes(graph, "diagnostic")[0]
    ordered = [diagnostic["evidence_excerpt"], *evidence]
    return "\n".join(dict.fromkeys(text for text in ordered if text))


def route_feedback(
    graph: dict[str, Any],
    *,
    previous_graphs: list[dict[str, Any]] | None = None,
    examples_available: bool = True,
    character_budget: int = 2400,
) -> dict[str, Any]:
    """选择下一轮反馈表示与检索动作；该 v1 是可解释规则基线。"""

    validate_error_state_graph(graph)
    history = previous_graphs or []
    for item in history:
        validate_error_state_graph(item)
    if character_budget < 200:
        raise ValueError("character_budget 至少为 200")

    category = graph["current_state"]["category"]
    repeated = bool(history) and history[-1]["current_state"]["category"] == category
    if category in INFRASTRUCTURE:
        action, representation, retrieval = "stop_infrastructure", "none", "none"
        payload = "基础设施错误不应作为普通证明反馈继续消耗生成预算。"
        reason = "基础设施事件与证明错误分离。"
    elif category == "ok":
        action, representation, retrieval = "stop_success", "none", "none"
        payload = "Lean 已验证通过。"
        reason = "已达到内核验证终点。"
    elif repeated:
        action, representation = "repair", "raw_plus_structured"
        retrieval = "diagnostic" if examples_available else "none"
        payload = _structured_payload(graph) + "\n原始证据：\n" + _raw_payload(graph)
        reason = "同类错误连续出现，扩大到原始证据并刷新错误驱动检索。"
    elif category == "syntax":
        action, representation, retrieval = "repair", "raw", "none"
        payload = _raw_payload(graph)
        reason = "语法错误优先保留编译器原文，避免结构化转换丢失 token 顺序。"
    elif category == "unknown_identifier":
        action, representation = "repair", "structured"
        retrieval = "diagnostic" if examples_available else "none"
        payload = _structured_payload(graph)
        reason = "未知标识符适合用符号和局部目标驱动检索。"
    else:
        action, representation, retrieval = "repair", "structured", "none"
        payload = _structured_payload(graph)
        reason = "先发送带原始证据链接的最小结构化反馈。"

    truncated = len(payload) > character_budget
    route = {
        "schema_version": PROTOCOL_VERSION,
        "case_id": graph["case_id"],
        "round": graph["current_state"]["round"],
        "category": category,
        "action": action,
        "representation": representation,
        "retrieval_strategy": retrieval,
        "repeated_category": repeated,
        "payload": payload[:character_budget],
        "payload_truncated": truncated,
        "character_budget": character_budget,
        "rationale": reason,
        "method_status": "deterministic_prototype_not_learned",
    }
    return route
