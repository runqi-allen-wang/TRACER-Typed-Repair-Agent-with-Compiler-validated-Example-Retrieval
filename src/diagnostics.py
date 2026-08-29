"""压缩并分类证明修复循环中的 Lean 编译反馈。"""

from __future__ import annotations

import re
from typing import Any


ERROR_RE = re.compile(r"^(?P<location>[^\r\n]+:\d+:\d+): error(?:\([^)]*\))?: (?P<message>.*)$")


def _classify_message(message: str) -> str:
    lower = message.lower()
    if "unknown identifier" in lower or "unknown constant" in lower:
        return "unknown_identifier"
    if "type mismatch" in lower or "application type mismatch" in lower:
        return "type_mismatch"
    if "unexpected token" in lower or "parser" in lower or "invalid syntax" in lower:
        return "syntax"
    if "unsolved goals" in lower or "unsolved goal" in lower:
        return "unsolved_goals"
    if "declaration has metavariables" in lower:
        return "metavariables"
    if "invalid `end`" in lower:
        return "scope_error"
    return "compile_error"


def classify_diagnostic_text(text: str) -> str:
    """Classify plain or AxProverBase-formatted Lean diagnostics.

    AxProverBase wraps compiler messages in a box-drawing error excerpt, so the
    original ``path:line:column: error: ...`` line may no longer be present.
    Scanning the complete text keeps the category useful without compiling the
    candidate again.
    """

    for line in text.splitlines():
        category = _classify_message(line)
        if category != "compile_error":
            return category
    return _classify_message(text)


def normalize_diagnostics(
    text: str,
    *,
    returncode: int | None = None,
    timed_out: bool = False,
    max_chars: int = 1200,
    max_errors: int = 6,
) -> dict[str, Any]:
    """返回适合下一轮模型提示的稳定短反馈。"""

    if timed_out or "编译超时" in text:
        return {
            "category": "timeout",
            "summary": "Lean 编译超过时间限制。请给出更短、更直接的局部证明。",
            "errors": [],
            "feedback": "类别=timeout；请缩短证明并避免引入额外搜索。",
            "truncated": False,
        }

    errors: list[dict[str, str]] = []
    loose_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = ERROR_RE.match(line)
        if match:
            errors.append(
                {
                    "location": match.group("location"),
                    "message": match.group("message")[:400],
                    "category": _classify_message(match.group("message")),
                }
            )
        elif "warning:" not in line.lower():
            loose_lines.append(line[:400])

    errors = errors[:max_errors]
    category = errors[0]["category"] if errors else (classify_diagnostic_text(text) if returncode else "ok")
    if errors:
        summary = "; ".join(f"{item['category']}: {item['message']}" for item in errors[:2])
    elif loose_lines:
        summary = loose_lines[0]
    else:
        summary = "Lean 编译通过。"
    feedback = f"类别={category}；摘要={summary[:700]}"
    truncated = len(feedback) > max_chars
    feedback = feedback[:max_chars]
    return {
        "category": category,
        "summary": summary[:700],
        "errors": errors,
        "feedback": feedback,
        "truncated": truncated,
    }
