"""Compact, deterministic feedback built from an existing Lean compile result.

This module intentionally does not invoke Lean or an LLM.  It is designed to
sit between AxProverBase's builder and proposer and reuse the builder's result.
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

try:
    from diagnostics import normalize_diagnostics
except ModuleNotFoundError as exc:
    if exc.name != "diagnostics":
        raise
    from src.diagnostics import normalize_diagnostics


SCHEMA_VERSION = "capsule-feedback.readable.v0.2"
SUPPORTED_STATE_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
AXPROVERBASE_COMMIT = "06dfadc9ab439755af5efcfe0add95bfef2733c7"
YXAI_MODEL_ID = "gpt-5.6-sol"
AXPROVER_YXAI_MODEL = f"openai:{YXAI_MODEL_ID}"
YXAI_BASE_URL = "https://yxai.chat/v1"
YXAI_WIRE_API = "responses"
YXAI_REASONING_EFFORT = "high"
YXAI_STORE_RESPONSES = False

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_WINDOWS_LOCATION_PATH_RE = re.compile(r"(?i)[A-Z]:[\\/][^\r\n]*?\.lean(?=:\d+:\d+)")
_UNIX_LOCATION_PATH_RE = re.compile(r"/[^\r\n:]*?\.lean(?=:\d+:\d+)")
_RELATIVE_LOCATION_PATH_RE = re.compile(r"(?<!\S)[A-Za-z0-9_.\\/-]+\.lean(?=:\d+:\d+)")
_LOCATION_RE = re.compile(r"(?<!\d)\d+:\d+(?!\d)")
_MVAR_RE = re.compile(r"(?:\?m\.\d+|\bmvar\.?\d+\b|\bmetavariable\s+\d+\b)", re.IGNORECASE)
_TEMP_FILE_RE = re.compile(r"\btmp_[A-Za-z0-9_.-]+\.lean\b")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_RE = re.compile(r"(?i)\b(?:sk|key)-[A-Za-z0-9._-]{8,}\b")
_NAMED_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|authorization)\b\s*[:=]\s*[^\s,;]+"
)


def _bounded_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return min(max(parsed, minimum), maximum)


def _redact_and_normalize(text: object, *, max_chars: int = 32768) -> str:
    value = _ANSI_RE.sub("", str(text or ""))
    value = _BEARER_RE.sub("Bearer <redacted>", value)
    value = _SECRET_RE.sub("<redacted-secret>", value)
    value = _NAMED_SECRET_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
    value = _WINDOWS_LOCATION_PATH_RE.sub("<path>", value)
    value = _UNIX_LOCATION_PATH_RE.sub("<path>", value)
    value = _RELATIVE_LOCATION_PATH_RE.sub("<path>", value)
    value = _LOCATION_RE.sub("<loc>", value)
    value = _MVAR_RE.sub("<mvar>", value)
    value = _TEMP_FILE_RE.sub("<temp>.lean", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:max_chars]


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "ok", "success", "passed"}:
            return True
        if normalized in {"false", "0", "no", "n", "failed", "failure", "error", ""}:
            return False
    return default


def normalized_feedback_text(category: str, diagnostic_text: str, goal_state: str = "") -> str:
    """直接比较脱敏后的有界诊断和目标文本，不生成派生摘要。"""

    payload = {
        "category": str(category),
        "diagnostic": _redact_and_normalize(diagnostic_text),
        "goal_state": _redact_and_normalize(goal_state),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return canonical


def _read_field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


class CapsuleFeedback:
    """Stateful formatter for one theorem's sequence of compile attempts."""

    def __init__(
        self,
        *,
        history_limit: int = 4,
        max_feedback_chars: int = 1600,
        feedback_limit: int = 64,
        state: Mapping[str, Any] | None = None,
    ) -> None:
        self.history_limit = _bounded_int(history_limit, 4, minimum=1, maximum=20)
        self.max_feedback_chars = _bounded_int(max_feedback_chars, 1600, minimum=320, maximum=12000)
        self.feedback_limit = _bounded_int(feedback_limit, 64, minimum=4, maximum=1000)
        state = state or {}
        state_version = state.get("schema_version")
        if state_version is not None and state_version not in SUPPORTED_STATE_SCHEMA_VERSIONS:
            raise ValueError(f"unsupported CapsuleFeedback state schema: {state_version}")
        self._attempt_count = _bounded_int(state.get("attempt_count"), 0, minimum=0, maximum=1_000_000)
        counts = state.get("feedback_counts", {})
        bounded_counts = list(counts.items())[-self.feedback_limit :] if isinstance(counts, Mapping) else []
        self._feedback_counts: OrderedDict[str, int] = OrderedDict(
            (str(key), _bounded_int(count, 0, minimum=0, maximum=1_000_000))
            for key, count in bounded_counts
        )
        history = state.get("history", [])
        self._history = [self._clean_history_entry(item) for item in history if isinstance(item, Mapping)]
        self._history = self._history[-self.history_limit :]

    @classmethod
    def from_state(
        cls,
        state: Mapping[str, Any],
        *,
        history_limit: int = 4,
        max_feedback_chars: int = 1600,
        feedback_limit: int = 64,
    ) -> "CapsuleFeedback":
        return cls(
            history_limit=history_limit,
            max_feedback_chars=max_feedback_chars,
            feedback_limit=feedback_limit,
            state=state,
        )

    @staticmethod
    def _clean_history_entry(item: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "round": _bounded_int(item.get("round"), 1, minimum=1, maximum=1_000_000),
            "compile_ok": _coerce_bool(item.get("compile_ok", False)),
            "category": str(item.get("category", "compile_error"))[:80],
            "feedback_text": str(item.get("feedback_text", "")),
            "repeat_count": _bounded_int(item.get("repeat_count"), 1, minimum=1, maximum=1_000_000),
            "consecutive_repeat_count": _bounded_int(
                item.get("consecutive_repeat_count"), 1, minimum=1, maximum=1_000_000
            ),
            "drift_kind": str(item.get("drift_kind", "initial"))[:40],
            "summary": _redact_and_normalize(item.get("summary", ""), max_chars=240),
        }

    def export_state(self) -> dict[str, Any]:
        """Return bounded JSON-serializable state for the next attempt."""

        return {
            "schema_version": SCHEMA_VERSION,
            "attempt_count": self._attempt_count,
            "feedback_counts": dict(self._feedback_counts),
            "history": [dict(item) for item in self._history],
        }

    def observe(
        self,
        *,
        compile_ok: bool,
        diagnostic_text: str = "",
        returncode: int | None = None,
        timed_out: bool = False,
        goal_state: str = "",
        round_no: int | None = None,
        category_hint: str | None = None,
    ) -> dict[str, Any]:
        """Consume one already-computed compiler result and return compact feedback."""

        self._attempt_count += 1
        round_no = _bounded_int(round_no, self._attempt_count, minimum=1, maximum=1_000_000)
        effective_returncode = returncode
        if effective_returncode is None:
            effective_returncode = 0 if compile_ok else 1
        normalized = normalize_diagnostics(
            str(diagnostic_text or ""),
            returncode=effective_returncode,
            timed_out=timed_out,
        )
        category = str(category_hint or normalized.get("category") or ("ok" if compile_ok else "compile_error"))
        if compile_ok:
            category = "ok"
        summary_source = normalized.get("summary") or goal_state or diagnostic_text
        summary = _redact_and_normalize(summary_source, max_chars=360)
        if not summary:
            summary = "Lean build succeeded." if compile_ok else "Lean build failed without diagnostic text."

        feedback_text = normalized_feedback_text(category, diagnostic_text, goal_state)
        repeat_count = self._feedback_counts.get(feedback_text, 0) + 1
        self._feedback_counts[feedback_text] = repeat_count
        self._feedback_counts.move_to_end(feedback_text)
        while len(self._feedback_counts) > self.feedback_limit:
            self._feedback_counts.popitem(last=False)
        previous = self._history[-1] if self._history else None

        if previous is None:
            drift_kind = "initial"
        elif compile_ok and not previous["compile_ok"]:
            drift_kind = "resolved"
        elif not compile_ok and previous["compile_ok"]:
            drift_kind = "regressed"
        elif feedback_text == previous["feedback_text"]:
            drift_kind = "none"
        elif category != previous["category"]:
            drift_kind = "category_changed"
        else:
            drift_kind = "diagnostic_changed"

        consecutive_repeat_count = (
            previous["consecutive_repeat_count"] + 1
            if previous is not None and feedback_text == previous["feedback_text"]
            else 1
        )
        diagnostic_drift = drift_kind in {"regressed", "category_changed", "diagnostic_changed"}
        entry = {
            "round": round_no,
            "compile_ok": bool(compile_ok),
            "category": category,
            "feedback_text": feedback_text,
            "repeat_count": repeat_count,
            "consecutive_repeat_count": consecutive_repeat_count,
            "drift_kind": drift_kind,
            "summary": summary[:240],
        }
        self._history.append(entry)
        self._history = self._history[-self.history_limit :]
        compact_history = [dict(item) for item in self._history]
        prompt_feedback = self._format_prompt(entry, compact_history)

        return {
            "schema_version": SCHEMA_VERSION,
            "source": "existing_axprover_compile_result",
            **entry,
            "diagnostic_drift": diagnostic_drift,
            "goal_state": _redact_and_normalize(goal_state, max_chars=500),
            "compact_history": compact_history,
            "prompt_feedback": prompt_feedback,
        }

    def observe_ax(self, result: object, *, round_no: int | None = None) -> dict[str, Any]:
        """Consume Ax's ``(success, message)`` tuple or a FeedbackMessage-like object."""

        if isinstance(result, tuple) and len(result) == 2:
            compile_ok, message = result
            return self.observe(
                compile_ok=_coerce_bool(compile_ok),
                diagnostic_text=str(message or ""),
                round_no=round_no,
            )

        feedback_type = str(_read_field(result, "feedback_type", ""))
        if feedback_type == "build_success":
            return self.observe(compile_ok=True, diagnostic_text="Build successful", round_no=round_no)
        if feedback_type == "sorries_goal_state":
            goal_state = str(_read_field(result, "goal_state_at_sorries", ""))
            count = _bounded_int(_read_field(result, "sorry_count", 1), 1, minimum=1, maximum=1_000_000)
            return self.observe(
                compile_ok=False,
                diagnostic_text=f"Unsolved goals at {count} sorry location(s).",
                goal_state=goal_state,
                round_no=round_no,
                category_hint="unsolved_goals",
            )

        compile_ok = _coerce_bool(
            _read_field(result, "compile_ok", _read_field(result, "ok", False))
        )
        message = _read_field(result, "error_output", None)
        if message is None:
            message = _read_field(result, "message", _read_field(result, "diagnostics", ""))
        return self.observe(
            compile_ok=compile_ok,
            diagnostic_text=str(message or ""),
            returncode=_read_field(result, "returncode", None),  # type: ignore[arg-type]
            timed_out=_coerce_bool(_read_field(result, "timed_out", False)),
            goal_state=str(_read_field(result, "goal_state", "") or ""),
            round_no=round_no,
        )

    def _format_prompt(self, current: Mapping[str, Any], history: list[dict[str, Any]]) -> str:
        lines = [
            "CAPSULE FEEDBACK (deterministic; no extra Lean build or LLM call)",
            f"category={current['category']}",
            f"repeat_count={current['repeat_count']}",
            f"consecutive_repeat_count={current['consecutive_repeat_count']}",
            f"drift={current['drift_kind']}",
            f"current={current['summary']}",
            "recent_history:",
        ]
        for item in history:
            lines.append(
                "- round={round} category={category} "
                "repeat={repeat_count} drift={drift_kind} summary={summary}".format(**item)
            )
        return "\n".join(lines)[: self.max_feedback_chars].rstrip()
