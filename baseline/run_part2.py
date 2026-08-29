"""Run pairing-ready Part 2 CapsuleFeedback experiments through the Ax API.

The upstream Ax CLI intentionally emits only ``success/error/summary``.  This
runner keeps the full ``ProverAgentState`` so Part 2 can produce the same
per-task JSONL contract as Part 1 and pass the strict pairing gate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compiler import CANDIDATE_POLICY  # noqa: E402
from leancapsule.ax_integration import (  # noqa: E402
    AX_INTEGRATION_VERSION,
    FEEDBACK_MODES,
    FirstRoundCandidateCache,
    enforce_ax_part2_config,
    install_axproverbase_capsule_feedback,
)
from leancapsule.feedback import (  # noqa: E402
    AXPROVERBASE_COMMIT,
    AXPROVER_YXAI_MODEL,
    YXAI_BASE_URL,
    YXAI_REASONING_EFFORT,
    YXAI_STORE_RESPONSES,
    YXAI_WIRE_API,
)


_CAPSULE_STATE_FILE_RE = re.compile(r"^session-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.json(?:\.tmp)?$")


def _read(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _proposal_messages(state: object) -> list[object]:
    messages = list(_read(state, "messages", []) or [])
    return [message for message in messages if _read(message, "type") == "proposal"]


def _is_repeated_feedback_event(event: Mapping[str, Any]) -> bool:
    try:
        return int(event.get("repeat_count", 1) or 1) > 1
    except (TypeError, ValueError):
        return False


def _contract_from_config(config: object) -> dict[str, Any]:
    prover = _read(config, "prover")
    enforce_ax_part2_config(prover)
    llm = _read(prover, "prover_llm")
    provider = _read(llm, "provider_config", {})
    reasoning = _read(provider, "reasoning", {})
    profile = _read(provider, "profile", {})
    memory = _read(prover, "memory_config")
    summary = _read(prover, "summarize_output")
    runtime = _read(config, "runtime")

    contract = {
        "model": str(_read(llm, "model", "")),
        "provider_config": {
            "base_url": str(_read(provider, "base_url", "")).rstrip("/"),
            "wire_api": YXAI_WIRE_API,
            "use_responses_api": _read(provider, "use_responses_api"),
            "store": _read(provider, "store"),
            "reasoning": {"effort": str(_read(reasoning, "effort", ""))},
            "output_version": str(_read(provider, "output_version", "")),
            "max_tokens": _read(provider, "max_tokens"),
            "profile": {"max_input_tokens": _read(profile, "max_input_tokens")},
        },
        "budget": {
            "max_iterations": int(_read(prover, "max_iterations", 0)),
            "max_input_tokens": int(_read(profile, "max_input_tokens", 0)),
            "max_tool_calling_iterations": int(
                _read(runtime, "max_tool_calling_iterations", 0)
            ),
        },
        "memory_processor": str(_read(memory, "class_name", "")),
        "summary_enabled": bool(_read(summary, "enabled", True)),
    }
    provider_contract = contract["provider_config"]
    errors: list[str] = []
    allowed_provider_keys = {
        "base_url",
        "max_tokens",
        "output_version",
        "profile",
        "reasoning",
        "store",
        "use_responses_api",
    }
    if isinstance(provider, Mapping):
        unexpected_provider_keys = sorted(set(provider) - allowed_provider_keys)
        if unexpected_provider_keys:
            errors.append(
                "provider_config contains unsupported keys: "
                + ", ".join(unexpected_provider_keys)
            )
    if contract["model"] != AXPROVER_YXAI_MODEL:
        errors.append(f"model must be {AXPROVER_YXAI_MODEL}")
    if provider_contract["base_url"] != YXAI_BASE_URL:
        errors.append(f"base_url must be {YXAI_BASE_URL}")
    if provider_contract["use_responses_api"] is not True:
        errors.append("use_responses_api must be true")
    if provider_contract["store"] is not YXAI_STORE_RESPONSES:
        errors.append("store must be false")
    if provider_contract["reasoning"]["effort"] != YXAI_REASONING_EFFORT:
        errors.append(f"reasoning effort must be {YXAI_REASONING_EFFORT}")
    if provider_contract["output_version"] != "responses/v1":
        errors.append("output_version must be responses/v1")
    if contract["memory_processor"] != "MemorylessProcessor":
        errors.append("Part 2 memory must be MemorylessProcessor")
    if contract["summary_enabled"]:
        errors.append("final LLM summary must be disabled")
    if contract["budget"]["max_iterations"] <= 0:
        errors.append("max_iterations must be positive")
    if errors:
        raise ValueError("invalid Part 2 experiment config: " + "; ".join(errors))
    return contract


def extract_record(
    target: str,
    state: object,
    prover: object,
    contract: Mapping[str, Any],
    *,
    feedback_mode: str = "capsule",
    task_metadata: Mapping[str, Any] | None = None,
    run_elapsed_ms: int = 0,
) -> dict[str, Any]:
    """Extract one pairing-ready Raw or Capsule condition record."""

    if feedback_mode not in FEEDBACK_MODES:
        raise ValueError(f"unsupported feedback mode: {feedback_mode}")

    metadata = dict(task_metadata or {})
    proposals = _proposal_messages(state)
    first = proposals[0] if proposals else None
    metrics_obj = _read(state, "metrics")
    metrics = metrics_obj.model_dump() if hasattr(metrics_obj, "model_dump") else {}
    state_item = _read(state, "item")
    location = _read(state_item, "location")
    theorem = str(metadata.get("theorem") or _read(location, "name", ""))
    module = str(metadata.get("module") or "")
    # FATE-M source declarations contain reference proofs, so TargetItem.is_proven
    # can be true even when this Agent run has not been approved.
    is_proven = bool(_read(state, "approved", False))
    rounds = int(_read(state, "iteration_count", len(proposals)) or len(proposals))

    node_calls = dict(getattr(prover, "_capsule_node_counts", {}) or {})
    llm_calls = dict(getattr(prover, "_capsule_llm_calls", {}) or {})
    usage = dict(getattr(prover, "_capsule_usage", {}) or {})
    prompt_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    completion_tokens = int(
        usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0
    )
    total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
    proposer_calls = int(llm_calls.get("proposer", 0) or 0)
    reviewer_calls = int(llm_calls.get("reviewer", 0) or 0)
    other_llm_calls = int(llm_calls.get("other", 0) or 0)
    provider_contract = dict(contract["provider_config"])
    feedback_events = [
        dict(event)
        for event in (getattr(prover, "_feedback_events", []) or [])
        if isinstance(event, Mapping)
    ]
    # Each feedback event is one observed diagnostic.  Count later occurrences
    # once; summing cumulative repeat_count values would double-count them.
    repeated_diagnostic_count = sum(
        _is_repeated_feedback_event(event) for event in feedback_events
    )
    memory_mode = "raw_feedback" if feedback_mode == "raw" else "capsule_feedback"

    return {
        "run_id": uuid.uuid4().hex[:12],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "task_id": str(metadata.get("id") or target),
        "target": target,
        "module": module,
        "theorem": theorem,
        "path": str(_read(location, "path", "")),
        "condition": feedback_mode,
        "feedback_mode": feedback_mode,
        "memory_mode": memory_mode,
        "memory_processor": "MemorylessProcessor",
        "integration_schema_version": AX_INTEGRATION_VERSION,
        "axproverbase_commit": AXPROVERBASE_COMMIT,
        "model": contract["model"],
        "base_url": provider_contract["base_url"],
        "wire_api": provider_contract["wire_api"],
        "use_responses_api": provider_contract["use_responses_api"],
        "store": provider_contract["store"],
        "reasoning_effort": provider_contract["reasoning"]["effort"],
        "provider_config": provider_contract,
        "budget": dict(contract["budget"]),
        "candidate_policy": dict(CANDIDATE_POLICY),
        "compile_ok": is_proven,
        "success_node": rounds if is_proven else None,
        "rounds": rounds,
        "iteration_count": metrics.get("number_of_iterations", rounds),
        "compilation_error_count": metrics.get("compilation_error_count", 0),
        "build_timeout_count": metrics.get("build_timeout_count", 0),
        "reviewer_rejections": metrics.get("reviewer_rejections", 0),
        "max_iterations_reached": metrics.get("max_iterations_reached", False),
        "run_elapsed_ms": run_elapsed_ms,
        "node_calls": node_calls,
        "calls": {
            "proposer_calls": proposer_calls,
            "reviewer_calls": reviewer_calls,
            "memory_calls": 0,
            "other_llm_calls": other_llm_calls,
            "tool_calls": int(getattr(prover, "_capsule_tool_calls", 0) or 0),
            "compiler_calls": int(node_calls.get("builder", 0) or 0),
            "capsule_llm_calls": 0,
            "capsule_compiler_calls": 0,
        },
        "call_count": proposer_calls + reviewer_calls + other_llm_calls,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "estimated_cost_usd": None,
        "first_round_candidate": str(_read(first, "code", "")) if first else "",
        "first_round_reasoning": str(_read(first, "reasoning", "")) if first else "",
        "first_round_imports": list(_read(first, "imports", []) or []) if first else [],
        "first_round_opens": list(_read(first, "opens", []) or []) if first else [],
        "candidate_count": len(proposals),
        "feedback_events": feedback_events,
        "diagnostic_event_count": len(feedback_events),
        "repeated_diagnostic_count": repeated_diagnostic_count,
        "api_error_count": 0,
    }


async def run_target(
    target: str,
    folder: str,
    config_yaml: str,
    *,
    feedback_mode: str = "capsule",
    telemetry_path: str | Path | None = None,
    state_dir: str | Path | None = None,
    first_round_cache_path: str | Path | None = None,
    task_metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from ax_prover.config import Config
    from ax_prover.prover.agent import ProverAgent
    from ax_prover.runtime import Runtime
    from ax_prover.tools import create_tool_lifespans
    from ax_prover.utils import (
        load_env_secrets,
        merge_configs,
        parse_prove_target,
        prove_single_item,
    )

    if feedback_mode not in FEEDBACK_MODES:
        raise ValueError(f"unsupported feedback mode: {feedback_mode}")
    install_axproverbase_capsule_feedback(
        feedback_mode=feedback_mode,
        telemetry_path=telemetry_path,
        state_dir=state_dir,
        first_round_cache_path=first_round_cache_path,
    )
    load_env_secrets(folder)
    # Do not inherit upstream default.yaml: it selects Claude, and OmegaConf's
    # deep merge otherwise leaves Claude-only ``betas``/``thinking`` keys in
    # this OpenAI-compatible provider request.
    config = merge_configs([Config(), config_yaml], folder=folder)
    contract = _contract_from_config(config)
    tool_lifespans = await create_tool_lifespans(config.prover.proposer_tools)
    records: list[dict[str, Any]] = []
    async with Runtime.open(config.runtime, folder, tool_lifespans) as runtime:
        items = await parse_prove_target(runtime.lean_interact_server, folder, target)
        for item in items:
            prover = await ProverAgent.create(config=config.prover, runtime=runtime)
            thread_id = f"part3_{feedback_mode}_{item.location.name}_{uuid.uuid4().hex[:6]}"
            started = time.perf_counter()
            state = await prove_single_item(prover, item, thread_id=thread_id)
            records.append(
                extract_record(
                    target,
                    state,
                    prover,
                    contract,
                    feedback_mode=feedback_mode,
                    task_metadata=task_metadata,
                    run_elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            )
    return records


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} must be a JSON object")
        rows.append(value)
    return rows


def validate_inputs(
    rows: list[dict[str, Any]], cache_path: Path
) -> list[dict[str, Any]]:
    """Fail before any live call if the paired inputs are incomplete or drifted."""

    if not rows:
        raise ValueError("baseline JSONL is empty")
    cache = FirstRoundCandidateCache(cache_path)
    seen: set[str] = set()
    for row_no, row in enumerate(rows, start=1):
        task_id = str(row.get("task_id") or "")
        target = str(row.get("target") or "")
        module = str(row.get("module") or "")
        theorem = str(row.get("theorem") or "")
        candidate = str(row.get("first_round_candidate") or "")
        reasoning = row.get("first_round_reasoning")
        imports = row.get("first_round_imports")
        opens = row.get("first_round_opens")
        if not task_id or not target or not module or not theorem or not candidate.strip():
            raise ValueError(
                f"baseline row {row_no} requires task_id, target, module, theorem, "
                "and first_round_candidate"
            )
        if target != f"{module}:{theorem}":
            raise ValueError(f"baseline row {row_no} target does not match module/theorem")
        if not isinstance(reasoning, str):
            raise ValueError(f"baseline row {row_no} first_round_reasoning must be a string")
        if isinstance(imports, str) or not isinstance(imports, list):
            raise ValueError(f"baseline row {row_no} first_round_imports must be a list")
        if isinstance(opens, str) or not isinstance(opens, list):
            raise ValueError(f"baseline row {row_no} first_round_opens must be a list")
        if not all(isinstance(item, str) for item in imports):
            raise ValueError(
                f"baseline row {row_no} first_round_imports entries must be strings"
            )
        if not all(isinstance(item, str) for item in opens):
            raise ValueError(
                f"baseline row {row_no} first_round_opens entries must be strings"
            )
        if task_id in seen:
            raise ValueError(f"duplicate baseline task_id: {task_id}")
        seen.add(task_id)
        cached = cache.get(target)
        if cached["code"] != candidate:
            raise ValueError(f"first-round code cache mismatch for {target}")
        if cached["reasoning"] != reasoning:
            raise ValueError(f"first-round reasoning cache mismatch for {target}")
        if cached["imports"] != imports:
            raise ValueError(f"first-round imports cache mismatch for {target}")
        if cached["opens"] != opens:
            raise ValueError(f"first-round opens cache mismatch for {target}")
    return rows


def prepare_run_artifacts(
    output_path: Path,
    *,
    state_dir: Path | None,
    metrics_path: Path | None,
    overwrite: bool,
    protected_paths: tuple[Path, ...] = (),
) -> None:
    """Require a fresh formal run and reset only known experiment artifacts."""

    output_resolved = output_path.resolve()
    metrics_resolved = metrics_path.resolve() if metrics_path is not None else None
    protected = {path.resolve() for path in protected_paths}
    if output_resolved in protected:
        raise ValueError("Part 2 output path overlaps a protected input file")
    if metrics_resolved is not None:
        if metrics_resolved == output_resolved:
            raise ValueError("CAPSULE_FEEDBACK_METRICS must differ from the Part 2 output")
        if metrics_resolved in protected:
            raise ValueError("CAPSULE_FEEDBACK_METRICS overlaps a protected input file")

    state_entries: list[Path] = []
    if state_dir is not None and state_dir.exists():
        if not state_dir.is_dir():
            raise ValueError("CAPSULE_FEEDBACK_STATE_DIR must be a directory")
        state_entries = list(state_dir.iterdir())
        unexpected = [
            entry
            for entry in state_entries
            if entry.is_symlink()
            or not entry.is_file()
            or _CAPSULE_STATE_FILE_RE.fullmatch(entry.name) is None
        ]
        if unexpected:
            names = ", ".join(sorted(entry.name for entry in unexpected)[:5])
            raise ValueError(
                "CAPSULE_FEEDBACK_STATE_DIR must be a dedicated state directory; "
                f"unexpected entries: {names}"
            )

    existing: list[str] = []
    if output_path.exists() and output_path.stat().st_size:
        existing.append(str(output_path))
    if metrics_path is not None and metrics_path.exists() and metrics_path.stat().st_size:
        existing.append(str(metrics_path))
    if state_entries:
        existing.append(f"{state_dir} ({len(state_entries)} state files)")
    if existing and not overwrite:
        raise ValueError(
            "existing Part 2 artifacts would contaminate a fresh run: "
            + "; ".join(existing)
            + "; choose fresh paths or pass --overwrite"
        )

    if overwrite:
        if output_path.exists() and output_path.is_file():
            output_path.write_text("", encoding="utf-8")
        if metrics_path is not None and metrics_path.exists() and metrics_path.is_file():
            metrics_path.write_text("", encoding="utf-8")
        for state_path in state_entries:
            state_path.unlink()

    if output_path.exists() and not output_path.is_file():
        raise ValueError("Part 2 output path must be a file")
    if metrics_path is not None and metrics_path.exists() and not metrics_path.is_file():
        raise ValueError("CAPSULE_FEEDBACK_METRICS must be a file")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if metrics_path is not None:
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--folder", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--feedback",
        choices=sorted(FEEDBACK_MODES),
        default="capsule",
        help="Feedback condition to run (default: capsule)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace a non-empty output file instead of refusing to create duplicate task rows",
    )
    args = parser.parse_args(argv)

    cache_value = os.environ.get("CAPSULE_FIRST_ROUND_CACHE", "")
    if not cache_value:
        print("CAPSULE_FIRST_ROUND_CACHE is required", file=sys.stderr)
        return 2
    try:
        rows = validate_inputs(_read_jsonl(args.baseline), Path(cache_value))
        if args.limit is not None:
            if args.limit <= 0:
                raise ValueError("--limit must be positive")
            rows = rows[: args.limit]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Part 2 preflight failed: {exc}", file=sys.stderr)
        return 2

    state_value = os.environ.get(
        "AX_FEEDBACK_STATE_DIR", os.environ.get("CAPSULE_FEEDBACK_STATE_DIR", "")
    )
    metrics_value = os.environ.get(
        "AX_FEEDBACK_METRICS", os.environ.get("CAPSULE_FEEDBACK_METRICS", "")
    )
    if args.feedback == "raw" and state_value:
        print("Part 3 preflight failed: Raw condition must not use Capsule state", file=sys.stderr)
        return 2
    try:
        prepare_run_artifacts(
            args.out,
            state_dir=Path(state_value) if state_value else None,
            metrics_path=Path(metrics_value) if metrics_value else None,
            overwrite=args.overwrite,
            protected_paths=(args.baseline, Path(cache_value)),
        )
    except (OSError, ValueError) as exc:
        print(f"Part 2 preflight failed: {exc}", file=sys.stderr)
        return 2

    failures = 0
    with args.out.open("a", encoding="utf-8", newline="\n") as stream:
        for index, row in enumerate(rows, start=1):
            target = str(row["target"])
            metadata = {
                "id": row["task_id"],
                "module": row.get("module", ""),
                "theorem": row.get("theorem", ""),
            }
            try:
                records = asyncio.run(
                    run_target(
                        target,
                        args.folder,
                        args.config,
                        feedback_mode=args.feedback,
                        telemetry_path=metrics_value or None,
                        state_dir=state_value or None,
                        first_round_cache_path=cache_value,
                        task_metadata=metadata,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[{index}/{len(rows)}] {target}: ERROR {exc}")
                failures += 1
                continue
            if not records:
                print(f"[{index}/{len(rows)}] {target}: ERROR no result record")
                failures += 1
                continue
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
                print(
                    f"[{index}/{len(rows)}] {record['theorem']}: "
                    f"proven={record['compile_ok']} rounds={record['rounds']} "
                    f"calls={record['call_count']} tokens={record['usage']['total_tokens']}"
                )
            stream.flush()
    print(f"wrote -> {args.out}")
    if failures:
        print(f"failed targets: {failures}/{len(rows)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
