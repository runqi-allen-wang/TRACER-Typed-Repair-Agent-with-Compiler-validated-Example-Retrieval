"""Compiler Feedback v1：构造并校验可审计的三层编译反馈记录。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from diagnostics import normalize_diagnostics
from leancapsule.privacy import redact_text
from provider import redact_sensitive_text


PROTOCOL_VERSION = "tracer-compiler-feedback-v1"
LAYERS = ("raw", "normalized", "structured")
ALLOWED_ORIGINS = {"lean_compiler", "runner_timeout", "provider", "compiler_process"}
ALLOWED_CATEGORIES = {
    "unknown_identifier",
    "type_mismatch",
    "unsolved_goals",
    "syntax",
    "typeclass",
    "elaboration",
    "metavariables",
    "timeout",
    "provider_error",
    "compiler_unavailable",
    "compile_error",
}
ALLOWED_SIGNAL_KINDS = {
    "unknown_identifier",
    "actual_type",
    "expected_type",
    "goal",
    "typeclass_instance",
    "elaboration_message",
    "parser_message",
    "infrastructure_failure",
    "compiler_message",
}

_LOCATION_PREFIX = re.compile(
    r"(?m)^(?:[A-Za-z]:[\\/][^\r\n:]+|/(?:[^\s:/]+/)+[^\s:]+|"
    r"<(?:workspace|local-path)>[^\r\n:]*):\d+:\d+:"
)
_UNKNOWN = re.compile(r"(?i)unknown\s+(?:identifier|constant)\s+[`']?([^`'\s]+)[`']?")
_ACTUAL_TYPE = re.compile(r"(?is)has type\s*\n\s*([^\r\n]+)")
_EXPECTED_TYPE = re.compile(r"(?is)(?:expected to have type|but is expected to have type)\s*\n\s*([^\r\n]+)")
_GOAL = re.compile(r"(?m)^\s*(⊢\s*[^\r\n]+)")
_TYPECLASS = re.compile(r"(?is)failed to synthesize\s*\n?\s*([^\r\n]+)")
_ELABORATION_LINE = re.compile(
    r"(?im)^.*(?:failed to infer|declaration has metavariables|synthesize placeholder).*$"
)
_PARSER_LINE = re.compile(
    r"(?im)^.*(?:unexpected token|unexpected end of input|parser|invalid syntax).*$"
)


class FeedbackProtocolError(ValueError):
    """反馈记录不符合冻结协议。"""


def _clean_raw(text: object, roots: Iterable[Path] = ()) -> str:
    """只做凭据和本机路径脱敏，保留换行和诊断原文。"""

    value = redact_sensitive_text(text)
    return redact_text(value, tuple(roots)).replace("\r\n", "\n").replace("\r", "\n")


def _normalized_text(text: str) -> str:
    """移除位置和易变空白，但不丢弃后续诊断行。"""

    lines: list[str] = []
    for raw_line in text.splitlines():
        line = _LOCATION_PREFIX.sub("<path>:<loc>:", raw_line)
        line = re.sub(r"\b(?:mvar|metavariable)\.?\d+\b", "<mvar>", line, flags=re.IGNORECASE)
        line = re.sub(r"[ \t]+", " ", line).rstrip()
        if line.strip():
            lines.append(line)
    return "\n".join(lines)


def _first_evidence(text: str, category: str) -> str:
    patterns = {
        "unknown_identifier": _UNKNOWN,
        "type_mismatch": re.compile(r"(?im)^.*(?:application )?type mismatch.*$"),
        "unsolved_goals": re.compile(r"(?im)^.*unsolved goals?.*$"),
        "syntax": _PARSER_LINE,
        "typeclass": re.compile(r"(?im)^.*failed to synthesize.*$"),
        "elaboration": _ELABORATION_LINE,
        "metavariables": _ELABORATION_LINE,
        "timeout": re.compile(r"(?im)^.*(?:timed? out|超时).*$"),
        "provider_error": re.compile(r"(?im)^.*(?:provider|HTTP\s+\d{3}|service unavailable).*$"),
        "compiler_unavailable": re.compile(r"(?im)^.*(?:compiler unavailable|编译器不可用|not found|cannot find).*$"),
    }
    match = patterns.get(category, re.compile(r"(?m)^.+$")).search(text)
    if match:
        return match.group(0).strip()
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _feedback_category(text: str, fallback: str) -> str:
    """只为 v1 夹具细分诊断，不改变既有 Agent/Capsule 分类口径。"""

    lower = text.lower()
    if "unknown identifier" in lower or "unknown constant" in lower:
        return "unknown_identifier"
    if "type mismatch" in lower or "application type mismatch" in lower:
        return "type_mismatch"
    if any(term in lower for term in ("unexpected token", "unexpected end of input", "parser", "invalid syntax")):
        return "syntax"
    if "unsolved goals" in lower or "unsolved goal" in lower:
        return "unsolved_goals"
    if "failed to synthesize" in lower:
        return "typeclass"
    if "failed to infer" in lower or "synthesize placeholder" in lower:
        return "elaboration"
    return fallback


def _signal(kind: str, value: str, evidence: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "value": value.strip(),
        "evidence_excerpt": evidence.strip(),
    }


def _structured_signals(text: str, category: str) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []

    unknown = _UNKNOWN.search(text)
    if unknown:
        signals.append(_signal("unknown_identifier", unknown.group(1), unknown.group(0)))

    actual = _ACTUAL_TYPE.search(text)
    if actual:
        signals.append(_signal("actual_type", actual.group(1), actual.group(0)))
    expected = _EXPECTED_TYPE.search(text)
    if expected:
        signals.append(_signal("expected_type", expected.group(1), expected.group(0)))

    for goal in _GOAL.finditer(text):
        signals.append(_signal("goal", goal.group(1).removeprefix("⊢").strip(), goal.group(0)))

    typeclass = _TYPECLASS.search(text)
    if typeclass:
        signals.append(_signal("typeclass_instance", typeclass.group(1), typeclass.group(0)))

    elaboration = _ELABORATION_LINE.search(text)
    if elaboration:
        signals.append(_signal("elaboration_message", elaboration.group(0).strip(), elaboration.group(0)))

    parser = _PARSER_LINE.search(text)
    if parser:
        signals.append(_signal("parser_message", parser.group(0).strip(), parser.group(0)))

    if category in {"timeout", "provider_error", "compiler_unavailable"}:
        excerpt = _first_evidence(text, category)
        signals.append(_signal("infrastructure_failure", excerpt, excerpt))

    if not signals:
        excerpt = _first_evidence(text, category)
        if excerpt:
            signals.append(_signal("compiler_message", excerpt, excerpt))
    return signals


def build_feedback_record(
    *,
    case_id: str,
    diagnostic_text: object,
    compile_ok: bool,
    returncode: int | None,
    timed_out: bool = False,
    origin: str = "lean_compiler",
    round_no: int = 1,
    category_hint: str | None = None,
    roots: Iterable[Path] = (),
) -> dict[str, Any]:
    """从一次既有运行结果构造 raw/normalized/structured 三层记录。

    本函数不启动 Lean，也不调用模型。``category_hint`` 仅供无法由 Lean 文本
    自身表达的基础设施事件使用，并在记录中显式标记来源。
    """

    if not case_id or round_no < 1:
        raise FeedbackProtocolError("case_id 不能为空且 round 必须为正整数")
    if origin not in ALLOWED_ORIGINS:
        raise FeedbackProtocolError(f"未知诊断来源: {origin}")
    if compile_ok and (timed_out or category_hint is not None):
        raise FeedbackProtocolError("成功记录不得带超时或失败类别提示")
    if category_hint is not None and origin == "lean_compiler":
        raise FeedbackProtocolError("Lean 编译诊断不得用 category_hint 覆盖分类")
    if category_hint is not None and category_hint not in {
        "timeout",
        "provider_error",
        "compiler_unavailable",
    }:
        raise FeedbackProtocolError("category_hint 只允许标记基础设施错误")
    expected_metadata = {
        "runner_timeout": "timeout",
        "provider": "provider_error",
        "compiler_process": "compiler_unavailable",
    }
    if origin in expected_metadata and category_hint != expected_metadata[origin]:
        raise FeedbackProtocolError("基础设施来源与类别提示不一致")
    if origin == "runner_timeout" and not timed_out:
        raise FeedbackProtocolError("runner_timeout 必须设置 timed_out")
    if timed_out and origin != "runner_timeout":
        raise FeedbackProtocolError("timed_out 只能由 runner_timeout 来源记录")

    raw_text = _clean_raw(diagnostic_text, roots)
    if not compile_ok and not raw_text.strip():
        raise FeedbackProtocolError("失败记录必须保留脱敏后的原始诊断")

    effective_returncode = returncode
    if effective_returncode is None and origin == "lean_compiler":
        effective_returncode = 0 if compile_ok else 1
    normalized = normalize_diagnostics(
        raw_text,
        returncode=effective_returncode,
        timed_out=timed_out,
        max_chars=2400,
        max_errors=12,
    )
    inferred = str(normalized.get("category") or "compile_error")
    category = "ok" if compile_ok else str(category_hint or _feedback_category(raw_text, inferred))
    if category not in ALLOWED_CATEGORIES and category != "ok":
        raise FeedbackProtocolError(f"协议未登记的诊断类别: {category}")
    normalized["category"] = category
    normalized["diagnostic_text"] = _normalized_text(raw_text)

    category_evidence = "Lean 编译通过。" if compile_ok else _first_evidence(raw_text, category)
    record = {
        "schema_version": PROTOCOL_VERSION,
        "case_id": case_id,
        "round": round_no,
        "raw": {
            "origin": origin,
            "text": raw_text,
            "compile_ok": bool(compile_ok),
            "returncode": returncode,
            "timed_out": bool(timed_out),
        },
        "normalized": normalized,
        "structured": {
            "category": category,
            "category_source": "runtime_metadata" if category_hint else "diagnostic_text",
            "category_evidence": category_evidence,
            "signals": [] if compile_ok else _structured_signals(raw_text, category),
        },
    }
    validate_feedback_record(record)
    return record


def validate_feedback_record(record: dict[str, Any]) -> None:
    """拒绝缺层、无原文证据或字段不一致的反馈记录。"""

    if record.get("schema_version") != PROTOCOL_VERSION:
        raise FeedbackProtocolError("反馈协议版本不匹配")
    if not isinstance(record.get("case_id"), str) or not record["case_id"].strip():
        raise FeedbackProtocolError("case_id 非法")
    if type(record.get("round")) is not int or record["round"] < 1:
        raise FeedbackProtocolError("round 非法")
    if any(not isinstance(record.get(layer), dict) for layer in LAYERS):
        raise FeedbackProtocolError("raw/normalized/structured 三层必须同时存在")

    raw = record["raw"]
    normalized = record["normalized"]
    structured = record["structured"]
    if raw.get("origin") not in ALLOWED_ORIGINS:
        raise FeedbackProtocolError("raw.origin 非法")
    if not isinstance(raw.get("text"), str):
        raise FeedbackProtocolError("raw.text 必须是文本")
    if type(raw.get("compile_ok")) is not bool or type(raw.get("timed_out")) is not bool:
        raise FeedbackProtocolError("raw.compile_ok 与 raw.timed_out 必须是布尔值")
    if raw.get("returncode") is not None and type(raw["returncode"]) is not int:
        raise FeedbackProtocolError("raw.returncode 必须是整数或 null")
    if normalized.get("category") != structured.get("category"):
        raise FeedbackProtocolError("normalized 与 structured 类别不一致")
    if structured.get("category") not in ALLOWED_CATEGORIES | {"ok"}:
        raise FeedbackProtocolError("structured.category 非法")
    if any(not isinstance(normalized.get(key), str) for key in ("summary", "diagnostic_text")):
        raise FeedbackProtocolError("normalized.summary 与 diagnostic_text 必须是文本")
    if structured.get("category_source") not in {"diagnostic_text", "runtime_metadata"}:
        raise FeedbackProtocolError("structured.category_source 非法")
    if raw["origin"] == "lean_compiler" and structured["category_source"] != "diagnostic_text":
        raise FeedbackProtocolError("Lean 编译类别必须来源于诊断文本")
    infrastructure_by_origin = {
        "runner_timeout": "timeout",
        "provider": "provider_error",
        "compiler_process": "compiler_unavailable",
    }
    expected_category = infrastructure_by_origin.get(raw["origin"])
    if expected_category and (
        structured["category_source"] != "runtime_metadata"
        or structured["category"] != expected_category
    ):
        raise FeedbackProtocolError("基础设施来源、类别及分类来源不一致")
    if raw["origin"] == "runner_timeout" and not raw["timed_out"]:
        raise FeedbackProtocolError("runner_timeout 记录必须标记 timed_out")
    if raw["timed_out"] and raw["origin"] != "runner_timeout":
        raise FeedbackProtocolError("timed_out 与 raw.origin 不一致")
    if raw["compile_ok"] != (structured["category"] == "ok"):
        raise FeedbackProtocolError("raw.compile_ok 与结构化类别不一致")
    if not raw["compile_ok"] and not raw["text"].strip():
        raise FeedbackProtocolError("失败记录必须保留原始诊断")

    evidence = structured.get("category_evidence")
    if structured["category"] == "ok":
        if evidence != "Lean 编译通过。" or structured.get("signals") != []:
            raise FeedbackProtocolError("成功记录不得伪造失败信号")
    elif not isinstance(evidence, str) or not evidence or evidence not in raw["text"]:
        raise FeedbackProtocolError("structured.category 缺少可回溯的原始片段")

    signals = structured.get("signals")
    if not isinstance(signals, list) or (structured["category"] != "ok" and not signals):
        raise FeedbackProtocolError("失败记录必须包含至少一个结构化信号")
    for signal in signals:
        if not isinstance(signal, dict) or set(signal) != {"kind", "value", "evidence_excerpt"}:
            raise FeedbackProtocolError("结构化信号字段不符合冻结协议")
        if signal.get("kind") not in ALLOWED_SIGNAL_KINDS:
            raise FeedbackProtocolError("结构化信号类型非法")
        excerpt = signal.get("evidence_excerpt")
        if not isinstance(excerpt, str) or not excerpt or excerpt not in raw["text"]:
            raise FeedbackProtocolError("结构化信号缺少原始诊断片段")
        if not isinstance(signal.get("value"), str) or not signal["value"].strip():
            raise FeedbackProtocolError("结构化信号值不能为空")


def summarize_transitions(records: list[dict[str, Any]]) -> dict[str, Any]:
    """离线汇总相邻轮次错误转移；不把基础设施错误算作证明失败。"""

    for record in records:
        validate_feedback_record(record)
    ordered = sorted(records, key=lambda item: (item["case_id"], item["round"]))
    transitions: dict[str, int] = {}
    repeated = 0
    proof_failures = 0
    infrastructure = {"timeout", "provider_error", "compiler_unavailable"}
    previous: dict[str, Any] | None = None
    for record in ordered:
        category = record["structured"]["category"]
        if category not in infrastructure and category != "ok":
            proof_failures += 1
        if previous is not None and previous["case_id"] == record["case_id"]:
            left = previous["structured"]["category"]
            key = f"{left} -> {category}"
            transitions[key] = transitions.get(key, 0) + 1
            repeated += int(left == category)
        previous = record
    return {
        "schema_version": PROTOCOL_VERSION,
        "records": len(records),
        "proof_failure_records": proof_failures,
        "infrastructure_error_records": sum(
            item["structured"]["category"] in infrastructure for item in records
        ),
        "adjacent_transitions": transitions,
        "repeated_category_transitions": repeated,
    }
