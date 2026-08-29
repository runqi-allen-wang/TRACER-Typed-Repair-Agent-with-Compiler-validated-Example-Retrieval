"""AxProverBase integration for deterministic CapsuleFeedback.

The integration wraps Ax's existing builder node.  The original builder still
owns the only Lean invocation; this module only transforms the feedback object
returned by that node and therefore never invokes Lean or an LLM itself.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from uuid import uuid4
import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from langchain_core.runnables import RunnableConfig
except ModuleNotFoundError:
    # The core Capsule library remains importable without the optional Ax stack.
    RunnableConfig = dict[str, Any]  # type: ignore[misc,assignment]

try:
    from compiler import CANDIDATE_POLICY, full_theorem_safety_violation
    from diagnostics import classify_diagnostic_text
except ModuleNotFoundError as exc:
    if exc.name != "compiler":
        raise
    from src.compiler import CANDIDATE_POLICY, full_theorem_safety_violation
    from src.diagnostics import classify_diagnostic_text

from .feedback import (
    AXPROVERBASE_COMMIT,
    AXPROVER_YXAI_MODEL,
    YXAI_BASE_URL,
    YXAI_REASONING_EFFORT,
    YXAI_STORE_RESPONSES,
    YXAI_WIRE_API,
    CapsuleFeedback,
    normalized_feedback_text,
)


AX_INTEGRATION_VERSION = "ax-capsule-feedback.readable.v0.3"
DEFAULT_MAX_THEOREM_SESSIONS = 128
YXAI_MAX_INPUT_TOKENS = 65536
_PATCH_MARKER = "__leancapsule_part2_installed__"
_PATCH_MODE_ATTR = "__leancapsule_feedback_mode__"
_PATCH_OPTIONS_ATTR = "__leancapsule_feedback_options__"
FEEDBACK_MODES = frozenset({"raw", "capsule"})
MEMORY_CLASSES = frozenset({"MemorylessProcessor", "ExperienceProcessor"})


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _write(value: object, name: str, replacement: object) -> None:
    if isinstance(value, dict):
        value[name] = replacement
    else:
        setattr(value, name, replacement)


def _plain_value(value: object) -> object:
    """Convert config containers to values accepted by Ax's memory constructor."""

    if isinstance(value, Mapping):
        return {key: _plain_value(item) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain_value(getattr(value, field.name))
            for field in fields(value)
        }
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return {key: _plain_value(item) for key, item in attributes.items()}
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_plain_value(item) for item in value)
    return value


def _theorem_key(state: object) -> str:
    item = _read(state, "item")
    location = _read(item, "location")
    formatted = _read(location, "formatted_context")
    if formatted:
        return str(formatted)
    path = str(_read(location, "path", "<unknown-path>"))
    name = str(_read(location, "name", _read(item, "name", "<unknown-theorem>")))
    return f"{path}:{name}"


def _round_no(state: object) -> int:
    try:
        return max(1, int(_read(state, "iteration_count", 1)))
    except (TypeError, ValueError):
        return 1


def _iteration_count(state: object) -> int:
    try:
        return max(0, int(_read(state, "iteration_count", 0)))
    except (TypeError, ValueError):
        return 0


def _canonical_ax_target(theorem_key: str) -> str:
    """Normalize equivalent Lean path and module target spellings."""

    value = str(theorem_key).strip()
    if ":" not in value:
        raise ValueError(f"invalid Ax theorem target: {theorem_key!r}")
    module, theorem = value.rsplit(":", 1)
    module = module.strip().replace("\\", "/")
    while module.startswith("./"):
        module = module[2:]
    if module.endswith(".lean"):
        module = module[: -len(".lean")]
    module = module.replace("/", ".").strip(".")
    theorem = theorem.strip()
    if not module or not theorem:
        raise ValueError(f"invalid Ax theorem target: {theorem_key!r}")
    return f"{module}:{theorem}"


def validate_ax_proposal_safety(
    state: object,
    code: object,
    *,
    imports: object = (),
    opens: object = (),
) -> str | None:
    """Validate one full-theorem Ax proposal before it reaches Lean."""

    item = _read(state, "item")
    location = _read(item, "location")
    theorem_name = str(_read(location, "name", _read(item, "name", "")) or "")
    original_source = str(_read(item, "original_source", "") or "")
    if not theorem_name:
        return "Ax proposal safety gate cannot determine the target theorem name"
    if not original_source.strip():
        return "Ax proposal safety gate requires the original theorem source"
    if isinstance(imports, str) or not isinstance(imports, (list, tuple)):
        return "Ax proposal imports must be a list"
    if isinstance(opens, str) or not isinstance(opens, (list, tuple)):
        return "Ax proposal opens must be a list"
    return full_theorem_safety_violation(
        str(code or ""),
        expected_name=theorem_name,
        original_source=original_source,
        imports=[str(value) for value in imports],
        opens=[str(value) for value in opens],
    )


def enforce_ax_part2_config(
    config: object,
    *,
    memory_class: str = "MemorylessProcessor",
    memory_init_args: object = None,
) -> object:
    """Freeze the Part 2 model, memory strategy, and disabled summary.

    ``MemorylessProcessor`` is the default Part 2 condition.  The B arm uses
    ``ExperienceProcessor`` with the same frozen yxai ``prover_llm`` for its
    memory node, so its extra memory calls remain part of the measured budget.
    """

    if memory_class not in MEMORY_CLASSES:
        choices = ", ".join(sorted(MEMORY_CLASSES))
        raise ValueError(f"unsupported Ax memory class {memory_class!r}; choose {choices}")

    llm = _read(config, "prover_llm")
    if llm is None:
        raise ValueError("Ax Part 2 requires prover.prover_llm configuration")
    _write(llm, "model", AXPROVER_YXAI_MODEL)
    provider_config = _read(llm, "provider_config")
    if provider_config is None:
        provider_config = {}
        _write(llm, "provider_config", provider_config)
    _write(provider_config, "base_url", YXAI_BASE_URL)
    _write(provider_config, "use_responses_api", True)
    _write(provider_config, "store", YXAI_STORE_RESPONSES)
    _write(provider_config, "reasoning", {"effort": YXAI_REASONING_EFFORT})
    _write(provider_config, "output_version", "responses/v1")
    _write(provider_config, "max_tokens", None)
    profile = _read(provider_config, "profile")
    if profile is None:
        profile = {}
        _write(provider_config, "profile", profile)
    _write(profile, "max_input_tokens", YXAI_MAX_INPUT_TOKENS)

    memory = _read(config, "memory_config")
    if memory is None:
        raise ValueError("Ax Part 2 requires prover.memory_config configuration")
    _write(memory, "class_name", memory_class)
    if memory_class == "MemorylessProcessor":
        _write(memory, "init_args", {})
    else:
        init_args = _read(memory, "init_args", {})
        if init_args is None:
            init_args = {}
        if not isinstance(init_args, Mapping):
            raise ValueError("Ax ExperienceProcessor memory init_args must be a mapping")
        if memory_init_args is not None:
            if not isinstance(memory_init_args, Mapping):
                raise ValueError("memory_init_args must be a mapping")
            init_args = {**dict(init_args), **dict(memory_init_args)}
        else:
            init_args = dict(init_args)
        # Do not allow an imported/default config to silently select another
        # provider for the memory node. Ax's BaseMemory expects this argument
        # to be a mapping, while OmegaConf returns the interpolated LLMConfig
        # as a dataclass instance.
        memory_llm_config = _plain_value(llm)
        if not isinstance(memory_llm_config, Mapping):
            raise ValueError("Ax ExperienceProcessor llm_config must be a mapping")
        init_args["llm_config"] = dict(memory_llm_config)
        _write(memory, "init_args", init_args)

    summary = _read(config, "summarize_output")
    if summary is None:
        raise ValueError("Ax Part 2 requires prover.summarize_output configuration")
    _write(summary, "enabled", False)
    _write(summary, "llm", llm)
    return config


def _validate_feedback_mode(feedback_mode: str) -> str:
    mode = str(feedback_mode or "").strip().lower()
    if mode not in FEEDBACK_MODES:
        choices = ", ".join(sorted(FEEDBACK_MODES))
        raise ValueError(f"unsupported Ax feedback mode {feedback_mode!r}; choose {choices}")
    return mode


class CapsuleFeedbackSessions:
    """Bounded, theorem-keyed CapsuleFeedback sessions with optional persistence."""

    def __init__(
        self,
        *,
        history_limit: int = 4,
        max_feedback_chars: int = 1600,
        feedback_limit: int = 64,
        max_sessions: int = DEFAULT_MAX_THEOREM_SESSIONS,
        state_dir: str | Path | None = None,
    ) -> None:
        self.history_limit = history_limit
        self.max_feedback_chars = max_feedback_chars
        self.feedback_limit = feedback_limit
        self.max_sessions = max(1, min(int(max_sessions), 4096))
        self.state_dir = Path(state_dir) if state_dir else None
        self._sessions: OrderedDict[str, CapsuleFeedback] = OrderedDict()

    def _state_path(self, theorem_key: str) -> Path | None:
        """随机文件名只用于存储；读取时逐项比较完整定理键，不从键派生文件名。"""
        if self.state_dir is None:
            return None
        for path in sorted(self.state_dir.glob("session-*.json")):
            if path.is_symlink():
                raise ValueError("状态目录不允许符号链接")
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("theorem_key"), str):
                raise ValueError("状态文件缺少可读定理键")
            if value["theorem_key"] == theorem_key:
                return path
        return self.state_dir / ("session-" + str(uuid4()) + ".json")

    def _new_session(self, theorem_key: str) -> CapsuleFeedback:
        state: dict[str, Any] = {}
        state_path = self._state_path(theorem_key)
        if state_path is not None and state_path.exists():
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(f"CapsuleFeedback state is not an object: {state_path}")
            if loaded.get("theorem_key") != theorem_key or not isinstance(loaded.get("state"), dict):
                raise ValueError("状态文件与定理键不匹配")
            state = loaded["state"]
        return CapsuleFeedback(
            history_limit=self.history_limit,
            max_feedback_chars=self.max_feedback_chars,
            feedback_limit=self.feedback_limit,
            state=state,
        )

    def _persist(self, theorem_key: str, session: CapsuleFeedback) -> None:
        state_path = self._state_path(theorem_key)
        if state_path is None:
            return
        state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = state_path.with_name(state_path.name + ".tmp")
        temporary.write_text(
            json.dumps({"theorem_key": theorem_key, "state": session.export_state()}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(state_path)

    def observe(self, theorem_key: str, feedback: object, *, round_no: int) -> dict[str, Any]:
        session = self._sessions.get(theorem_key)
        if session is None:
            session = self._new_session(theorem_key)
            self._sessions[theorem_key] = session
        self._sessions.move_to_end(theorem_key)
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)
        result = session.observe_ax(feedback, round_no=round_no)
        self._persist(theorem_key, session)
        return result

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)


class RawFeedbackTracker:
    """Track Raw diagnostics for telemetry without changing Ax feedback."""

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = {}
        self._last: dict[str, str] = {}
        self._consecutive: dict[str, int] = {}

    def observe(self, theorem_key: str, feedback: object, *, round_no: int) -> dict[str, Any]:
        feedback_type = _feedback_type(feedback)
        goal_state = str(_read(feedback, "goal_state_at_sorries", "") or "")
        if feedback_type == "sorries_goal_state":
            diagnostic = goal_state
            category = "unsolved_goals"
        else:
            diagnostic = str(_read(feedback, "error_output", "") or "")
            category = classify_diagnostic_text(diagnostic)
        feedback_text = normalized_feedback_text(category, diagnostic, goal_state)
        counts = self._counts.setdefault(theorem_key, {})
        repeat_count = counts.get(feedback_text, 0) + 1
        counts[feedback_text] = repeat_count
        previous = self._last.get(theorem_key)
        if previous is None:
            drift_kind = "initial"
        elif previous == feedback_text:
            drift_kind = "none"
        else:
            drift_kind = "diagnostic_changed"
        consecutive = 1
        if previous == feedback_text:
            previous_consecutive = self._consecutive.get(theorem_key, 0)
            consecutive = previous_consecutive + 1
        self._consecutive[theorem_key] = consecutive
        self._last[theorem_key] = feedback_text
        return {
            "input_feedback_type": feedback_type,
            "category": category,
            "feedback_text": feedback_text,
            "repeat_count": repeat_count,
            "consecutive_repeat_count": consecutive,
            "drift_kind": drift_kind,
            "diagnostic_drift": drift_kind == "diagnostic_changed",
            "diagnostic_chars": min(len(diagnostic), 32768),
        }


class JsonlTelemetry:
    """Append redacted Part 2 telemetry as one compact JSON object per event."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None
        self._lock = threading.Lock()

    def append(self, event: Mapping[str, Any]) -> None:
        if self.path is None:
            return
        serialized = json.dumps(dict(event), ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(serialized + "\n")


class FirstRoundCandidateCache:
    """Strict target-to-ProposalMessage payload mapping produced by Part 1."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        loaded = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, Mapping):
            raise ValueError("first-round candidate cache must be a JSON object")
        self._candidates: dict[str, object] = {}
        for key, value in loaded.items():
            canonical = _canonical_ax_target(str(key))
            previous = self._candidates.get(canonical)
            if previous is not None and previous != value:
                raise ValueError(
                    f"conflicting first-round candidates for canonical target {canonical!r}"
                )
            self._candidates[canonical] = value

    def get(self, theorem_key: str) -> dict[str, Any]:
        canonical = _canonical_ax_target(theorem_key)
        if canonical not in self._candidates:
            raise KeyError(
                f"first-round candidate cache has no exact entry for {theorem_key!r}"
            )
        value = self._candidates[canonical]
        if isinstance(value, str):
            payload: dict[str, Any] = {"code": value}
        elif isinstance(value, Mapping):
            payload = dict(value)
        else:
            raise ValueError(f"invalid first-round candidate for {theorem_key!r}")
        code = str(
            payload.get("code")
            or payload.get("candidate")
            or payload.get("first_round_candidate")
            or ""
        )
        if not code.strip():
            raise ValueError(f"empty first-round candidate for {theorem_key!r}")
        if len(code) > 2_000_000:
            raise ValueError(f"first-round candidate is too large for {theorem_key!r}")
        reasoning = payload.get("reasoning", "Reused paired first-round candidate.")
        imports = payload.get("imports", [])
        opens = payload.get("opens", [])
        if not isinstance(reasoning, str):
            raise ValueError(f"first-round reasoning must be a string for {theorem_key!r}")
        if isinstance(imports, str) or not isinstance(imports, list):
            raise ValueError(f"first-round imports must be a list for {theorem_key!r}")
        if isinstance(opens, str) or not isinstance(opens, list):
            raise ValueError(f"first-round opens must be a list for {theorem_key!r}")
        if not all(isinstance(item, str) for item in imports):
            raise ValueError(f"first-round imports entries must be strings for {theorem_key!r}")
        if not all(isinstance(item, str) for item in opens):
            raise ValueError(f"first-round opens entries must be strings for {theorem_key!r}")
        return {
            "code": code,
            "reasoning": reasoning,
            "imports": list(imports),
            "opens": list(opens),
        }


def _feedback_type(feedback: object) -> str:
    return str(_read(feedback, "feedback_type", ""))


def _response_usage(response: object) -> dict[str, int]:
    usage = _read(response, "usage_metadata")
    if not isinstance(usage, Mapping):
        metadata = _read(response, "response_metadata", {})
        usage = _read(metadata, "token_usage", {})
    if not isinstance(usage, Mapping):
        usage = {}

    def value(*names: str) -> int:
        for name in names:
            candidate = usage.get(name)
            if isinstance(candidate, int) and not isinstance(candidate, bool):
                return max(0, candidate)
        return 0

    input_tokens = value("input_tokens", "prompt_tokens")
    output_tokens = value("output_tokens", "completion_tokens")
    total_tokens = value("total_tokens") or input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _capsule_event(
    *,
    theorem_key: str,
    round_no: int,
    input_feedback_type: str,
    payload: Mapping[str, Any],
    builder_elapsed_ms: float,
    capsule_elapsed_ms: float,
    memory_processor: str = "MemorylessProcessor",
    memory_llm_calls: int = 0,
) -> dict[str, Any]:
    return {
        "integration_schema_version": AX_INTEGRATION_VERSION,
        "feedback_mode": "capsule",
        "capsule_schema_version": payload["schema_version"],
        "axproverbase_commit": AXPROVERBASE_COMMIT,
        "model": AXPROVER_YXAI_MODEL,
        "base_url": YXAI_BASE_URL,
        "wire_api": YXAI_WIRE_API,
        "use_responses_api": True,
        "store": YXAI_STORE_RESPONSES,
        "reasoning_effort": YXAI_REASONING_EFFORT,
        "candidate_policy": dict(CANDIDATE_POLICY),
        "event_id": str(uuid4()),
        "theorem_name": theorem_key.rsplit(":", 1)[-1][:160],
        "round": round_no,
        "input_feedback_type": input_feedback_type,
        "category": payload["category"],
        "feedback_text": payload["feedback_text"],
        "repeat_count": payload["repeat_count"],
        "consecutive_repeat_count": payload["consecutive_repeat_count"],
        "drift_kind": payload["drift_kind"],
        "diagnostic_drift": payload["diagnostic_drift"],
        "feedback_chars": len(str(payload["prompt_feedback"])),
        "builder_elapsed_ms": round(builder_elapsed_ms, 3),
        "capsule_elapsed_ms": round(capsule_elapsed_ms, 3),
        "builder_result_reused": True,
        "capsule_compiler_calls": 0,
        "capsule_llm_calls": 0,
        "memory_llm_calls": memory_llm_calls,
        "memory_processor": memory_processor,
    }


def _raw_event(
    *,
    theorem_key: str,
    round_no: int,
    payload: Mapping[str, Any],
    builder_elapsed_ms: float,
    memory_processor: str = "MemorylessProcessor",
    memory_llm_calls: int = 0,
) -> dict[str, Any]:
    """Record Raw feedback without changing the Ax feedback object."""

    return {
        "integration_schema_version": AX_INTEGRATION_VERSION,
        "feedback_mode": "raw",
        "event_id": str(uuid4()),
        "axproverbase_commit": AXPROVERBASE_COMMIT,
        "model": AXPROVER_YXAI_MODEL,
        "base_url": YXAI_BASE_URL,
        "wire_api": YXAI_WIRE_API,
        "use_responses_api": True,
        "store": YXAI_STORE_RESPONSES,
        "reasoning_effort": YXAI_REASONING_EFFORT,
        "candidate_policy": dict(CANDIDATE_POLICY),
        "theorem_name": theorem_key.rsplit(":", 1)[-1][:160],
        "round": round_no,
        "input_feedback_type": payload["input_feedback_type"],
        "category": payload["category"],
        "feedback_text": payload["feedback_text"],
        "repeat_count": payload["repeat_count"],
        "consecutive_repeat_count": payload["consecutive_repeat_count"],
        "drift_kind": payload["drift_kind"],
        "diagnostic_drift": payload["diagnostic_drift"],
        "diagnostic_chars": payload["diagnostic_chars"],
        "builder_elapsed_ms": round(builder_elapsed_ms, 3),
        "builder_result_reused": False,
        "capsule_compiler_calls": 0,
        "capsule_llm_calls": 0,
        "memory_llm_calls": memory_llm_calls,
        "memory_processor": memory_processor,
    }


def install_axproverbase_capsule_feedback(
    *,
    agent_class: type | None = None,
    build_failed_class: type | None = None,
    proposal_class: type | None = None,
    feedback_mode: str = "capsule",
    telemetry_path: str | Path | None = None,
    state_dir: str | Path | None = None,
    first_round_cache_path: str | Path | None = None,
    memory_class: str = "MemorylessProcessor",
    memory_init_args: object = None,
) -> type:
    """Install the Raw/Capsule wrapper before Ax constructs ``ProverAgent``.

    Optional class injection keeps the integration testable without importing
    Ax's heavy runtime.  Production callers should omit it.
    """

    feedback_mode = _validate_feedback_mode(feedback_mode)
    if memory_class not in MEMORY_CLASSES:
        choices = ", ".join(sorted(MEMORY_CLASSES))
        raise ValueError(f"unsupported Ax memory class {memory_class!r}; choose {choices}")

    if agent_class is None or build_failed_class is None or proposal_class is None:
        try:
            from ax_prover.models.messages import BuildFailedFeedback, ProposalMessage
            from ax_prover.prover.agent import ProverAgent
        except ImportError as exc:
            raise RuntimeError(
                "AxProverBase is not installed; install the pinned Part 2 dependency first"
            ) from exc
        agent_class = agent_class or ProverAgent
        build_failed_class = build_failed_class or BuildFailedFeedback
        proposal_class = proposal_class or ProposalMessage

    options = {
        "feedback_mode": feedback_mode,
        "telemetry_path": telemetry_path,
        "state_dir": state_dir,
        "first_round_cache_path": first_round_cache_path,
        "memory_class": memory_class,
        "memory_init_args": memory_init_args,
    }
    setattr(agent_class, _PATCH_OPTIONS_ATTR, options)
    setattr(agent_class, _PATCH_MODE_ATTR, feedback_mode)
    if getattr(agent_class, _PATCH_MARKER, False):
        return agent_class

    original_init = agent_class.__init__
    original_builder = agent_class._builder_node
    original_memory = getattr(agent_class, "_memory_processor_node", None)
    original_proposer = getattr(agent_class, "_proposer_node", None)
    original_reviewer = getattr(agent_class, "_reviewer_node", None)
    original_chat = getattr(agent_class, "chat", None)
    def reject_unsafe_proposal(
        self: object,
        state: object,
        proposal: object,
        *,
        stage: str,
    ) -> str | None:
        code = _read(proposal, "code", "")
        violation = validate_ax_proposal_safety(
            state,
            code,
            imports=_read(proposal, "imports", []),
            opens=_read(proposal, "opens", []),
        )
        if violation is None:
            return None
        theorem_key = _theorem_key(state)
        self._capsule_feedback_telemetry.append(
            {
                "integration_schema_version": AX_INTEGRATION_VERSION,
                "event": "unsafe_proposal_rejected",
                "stage": stage,
                "event_id": str(uuid4()),
                "theorem_name": theorem_key.rsplit(":", 1)[-1][:160],
                "candidate_chars": len(str(code)),
                "candidate_policy": dict(CANDIDATE_POLICY),
                "reason": violation[:500],
                "rejected_before_builder": True,
            }
        )
        return violation

    def patched_init(self: object, config: object, runtime: object) -> None:
        active_options = getattr(type(self), _PATCH_OPTIONS_ATTR, {})
        active_memory_class = str(
            active_options.get("memory_class", "MemorylessProcessor")
        )
        active_memory_init_args = active_options.get("memory_init_args")
        enforce_ax_part2_config(
            config,
            memory_class=active_memory_class,
            memory_init_args=active_memory_init_args,
        )
        original_init(self, config, runtime)
        active_mode = _validate_feedback_mode(active_options.get("feedback_mode", "capsule"))
        self._capsule_memory_processor = active_memory_class
        telemetry_value = active_options.get("telemetry_path") or os.environ.get(
            "AX_FEEDBACK_METRICS", os.environ.get("CAPSULE_FEEDBACK_METRICS")
        )
        state_value = active_options.get("state_dir") or os.environ.get(
            "AX_FEEDBACK_STATE_DIR", os.environ.get("CAPSULE_FEEDBACK_STATE_DIR")
        )
        cache_value = active_options.get("first_round_cache_path") or os.environ.get(
            "CAPSULE_FIRST_ROUND_CACHE"
        )
        self._capsule_feedback_mode = active_mode
        self._capsule_feedback_sessions = (
            CapsuleFeedbackSessions(state_dir=state_value)
            if active_mode == "capsule"
            else None
        )
        self._raw_feedback_tracker = RawFeedbackTracker()
        self._feedback_events: list[dict[str, Any]] = []
        self._capsule_feedback_telemetry = JsonlTelemetry(telemetry_value)
        self._capsule_first_round_cache = (
            FirstRoundCandidateCache(cache_value)
            if cache_value
            else None
        )
        self._capsule_node_counts = {
            "proposer": 0,
            "proposer_uncached": 0,
            "shared_first_round": 0,
            "builder": 0,
            "memory": 0,
            "reviewer": 0,
        }
        self._capsule_active_llm_role = "other"
        self._capsule_llm_calls = {
            "proposer": 0,
            "reviewer": 0,
            "memory": 0,
            "other": 0,
        }
        self._capsule_tool_calls = 0
        self._capsule_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

        def instrument_llm_client(client: object, forced_role: str | None = None) -> None:
            """Count both the prover client and ExperienceProcessor's client."""

            if client is None:
                return
            original_ainvoke = getattr(client, "ainvoke", None)
            if original_ainvoke is None:
                return

            async def counted_ainvoke(*args: object, **kwargs: object) -> object:
                role = forced_role or self._capsule_active_llm_role
                if role not in self._capsule_llm_calls:
                    role = "other"
                self._capsule_llm_calls[role] += 1
                response = await original_ainvoke(*args, **kwargs)
                usage = _response_usage(response)
                for key, count in usage.items():
                    self._capsule_usage[key] += count
                tool_calls = _read(response, "tool_calls", [])
                if isinstance(tool_calls, list):
                    self._capsule_tool_calls += len(tool_calls)
                return response

            client.ainvoke = counted_ainvoke

        instrumented_clients: set[int] = set()
        for client, forced_role in (
            (getattr(self, "llm_client", None), None),
            (getattr(getattr(self, "memory", None), "llm", None), "memory"),
        ):
            if client is None or id(client) in instrumented_clients:
                continue
            instrument_llm_client(client, forced_role=forced_role)
            instrumented_clients.add(id(client))

    async def patched_builder(self: object, state: object) -> dict:
        last_proposal = _read(state, "last_proposal")
        if last_proposal is not None:
            violation = reject_unsafe_proposal(
                self, state, last_proposal, stage="builder_precompile_gate"
            )
            if violation is not None:
                return {
                    "messages": [
                        build_failed_class(
                            error_output=(
                                "TRACER candidate rejected before Lean build: " + violation
                            )
                        )
                    ]
                }
        self._capsule_node_counts["builder"] += 1
        builder_started = time.perf_counter()
        result = await original_builder(self, state)
        builder_elapsed_ms = (time.perf_counter() - builder_started) * 1000
        if not isinstance(result, dict):
            return result

        messages = result.get("messages")
        if not isinstance(messages, list):
            return result
        theorem_key = _theorem_key(state)
        current_round = _round_no(state)

        if getattr(self, "_capsule_feedback_mode", "capsule") == "raw":
            for feedback in messages:
                feedback_type = _feedback_type(feedback)
                if feedback_type not in {"build_failed", "sorries_goal_state"}:
                    continue
                payload = self._raw_feedback_tracker.observe(
                    theorem_key, feedback, round_no=current_round
                )
                event = _raw_event(
                    theorem_key=theorem_key,
                    round_no=current_round,
                    payload=payload,
                    builder_elapsed_ms=builder_elapsed_ms,
                    memory_processor=self._capsule_memory_processor,
                    memory_llm_calls=int(self._capsule_llm_calls.get("memory", 0) or 0),
                )
                self._feedback_events.append(dict(event))
                self._capsule_feedback_telemetry.append(event)
            return result

        transformed = []
        changed = False
        for feedback in messages:
            feedback_type = _feedback_type(feedback)
            if feedback_type not in {"build_failed", "sorries_goal_state"}:
                transformed.append(feedback)
                continue
            capsule_started = time.perf_counter()
            payload = self._capsule_feedback_sessions.observe(
                theorem_key, feedback, round_no=current_round
            )
            capsule_elapsed_ms = (time.perf_counter() - capsule_started) * 1000
            transformed.append(build_failed_class(error_output=payload["prompt_feedback"]))
            event = _capsule_event(
                theorem_key=theorem_key,
                round_no=current_round,
                input_feedback_type=feedback_type,
                payload=payload,
                builder_elapsed_ms=builder_elapsed_ms,
                capsule_elapsed_ms=capsule_elapsed_ms,
                memory_processor=self._capsule_memory_processor,
                memory_llm_calls=int(self._capsule_llm_calls.get("memory", 0) or 0),
            )
            self._feedback_events.append(dict(event))
            self._capsule_feedback_telemetry.append(event)
            changed = True
        if not changed:
            return result
        transformed_result = dict(result)
        transformed_result["messages"] = transformed
        return transformed_result

    async def counted_memory(self: object, *args: object, **kwargs: object) -> object:
        self._capsule_node_counts["memory"] += 1
        previous_role = self._capsule_active_llm_role
        self._capsule_active_llm_role = "memory"
        try:
            return await original_memory(self, *args, **kwargs)
        finally:
            self._capsule_active_llm_role = previous_role

    async def counted_proposer(
        self: object, state: object, config: RunnableConfig
    ) -> object:
        self._capsule_node_counts["proposer"] += 1
        if self._capsule_first_round_cache is not None and _iteration_count(state) == 0:
            theorem_key = _theorem_key(state)
            candidate = self._capsule_first_round_cache.get(theorem_key)
            location = _read(_read(state, "item"), "location")
            proposal = proposal_class(
                reasoning=candidate["reasoning"],
                code=candidate["code"],
                location=location,
                imports=candidate["imports"],
                opens=candidate["opens"],
            )
            self._capsule_node_counts["shared_first_round"] += 1

            self._capsule_feedback_telemetry.append(
                {
                    "integration_schema_version": AX_INTEGRATION_VERSION,
                    "event": "shared_first_round_candidate",
                    "event_id": str(uuid4()),
                    "feedback_mode": getattr(self, "_capsule_feedback_mode", "capsule"),
                    "theorem_name": theorem_key.rsplit(":", 1)[-1][:160],
                    "candidate_chars": len(candidate["code"]),
                    "proposer_llm_calls": 0,
                }
            )
            return {"messages": [proposal]}
        self._capsule_node_counts["proposer_uncached"] += 1
        previous_role = self._capsule_active_llm_role
        self._capsule_active_llm_role = "proposer"
        try:
            result = await original_proposer(self, state, config)
            return result
        finally:
            self._capsule_active_llm_role = previous_role

    async def counted_reviewer(
        self: object, state: object, config: RunnableConfig
    ) -> object:
        self._capsule_node_counts["reviewer"] += 1
        previous_role = self._capsule_active_llm_role
        self._capsule_active_llm_role = "reviewer"
        try:
            return await original_reviewer(self, state, config)
        finally:
            self._capsule_active_llm_role = previous_role

    async def counted_chat(self: object, *args: object, **kwargs: object) -> object:
        result = await original_chat(self, *args, **kwargs)
        self._capsule_feedback_telemetry.append(
            {
                "integration_schema_version": AX_INTEGRATION_VERSION,
                "event": "run_summary",
                "feedback_mode": getattr(self, "_capsule_feedback_mode", "capsule"),
                "axproverbase_commit": AXPROVERBASE_COMMIT,
                "model": AXPROVER_YXAI_MODEL,
                "base_url": YXAI_BASE_URL,
                "wire_api": YXAI_WIRE_API,
                "use_responses_api": True,
                "store": YXAI_STORE_RESPONSES,
                "reasoning_effort": YXAI_REASONING_EFFORT,
                "memory_processor": self._capsule_memory_processor,
                "memory_llm_calls": int(self._capsule_llm_calls.get("memory", 0) or 0),
                "capsule_llm_calls": 0,
                "capsule_compiler_calls": 0,
                "node_calls": dict(self._capsule_node_counts),
                "calls": {
                    "proposer_calls": self._capsule_llm_calls["proposer"],
                    "reviewer_calls": self._capsule_llm_calls["reviewer"],
                    "memory_calls": int(self._capsule_llm_calls.get("memory", 0) or 0),
                    "other_llm_calls": self._capsule_llm_calls["other"],
                    "tool_calls": self._capsule_tool_calls,
                    "capsule_llm_calls": 0,
                    "capsule_compiler_calls": 0,
                },
                "usage": dict(self._capsule_usage),
                "estimated_cost_usd": None,
            }
        )
        return result

    agent_class.__init__ = patched_init
    agent_class._builder_node = patched_builder
    if original_memory is not None:
        agent_class._memory_processor_node = counted_memory
    if original_proposer is not None:
        agent_class._proposer_node = counted_proposer
    if original_reviewer is not None:
        agent_class._reviewer_node = counted_reviewer
    if original_chat is not None:
        agent_class.chat = counted_chat
    setattr(agent_class, _PATCH_MARKER, True)
    return agent_class


__all__ = [
    "AX_INTEGRATION_VERSION",
    "CapsuleFeedbackSessions",
    "FEEDBACK_MODES",
    "MEMORY_CLASSES",
    "YXAI_MAX_INPUT_TOKENS",
    "FirstRoundCandidateCache",
    "JsonlTelemetry",
    "RawFeedbackTracker",
    "enforce_ax_part2_config",
    "install_axproverbase_capsule_feedback",
]
