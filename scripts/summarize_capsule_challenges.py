"""Run the isolated four-case LeanCapsule challenge feasibility pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compiler import find_project_root, lean_subprocess_environment, run_lean_file  # noqa: E402
from diagnostics import normalize_diagnostics  # noqa: E402
from leancapsule.diagnostics_key import diagnostic_key  # noqa: E402
from leancapsule.privacy import redact_text  # noqa: E402


DEFAULT_CASES = ROOT / "gallery_sources" / "challenge"
DEFAULT_RESULTS = ROOT / "results" / "capsule_challenges"
DEFAULT_REPORT = ROOT / "docs" / "CAPSULE_CHALLENGE_PILOT.md"


def ensure_elan_home() -> str | None:
    """Expose an existing Elan installation to TRACER's scratch-HOME subprocesses."""

    existing = os.environ.get("ELAN_HOME")
    if existing:
        return existing
    candidate = Path.home() / ".elan"
    if candidate.exists():
        os.environ["ELAN_HOME"] = str(candidate)
        return str(candidate)
    return None


def strict_ordered_diagnostics(text: str, roots: tuple[Path, ...] = ()) -> str:
    """Normalize only environment noise while retaining every ordered diagnostic line.

    This is a challenge-analysis observation, not the official diagnostic key and
    not a claim that text equality implies semantic equivalence.
    """

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(
        r"(?m)^.*?\.lean:\d+:\d+(?=:\s*(?:error|warning|info))",
        "<path>:<loc>",
        cleaned,
    )
    for root in roots:
        variants = {str(root), str(root).replace("\\", "/")}
        for value in variants:
            if value:
                cleaned = cleaned.replace(value, "<path>")
    cleaned = re.sub(r"\b\d+:\d+\b", "<loc>", cleaned)
    cleaned = re.sub(r"\b(?:mvar|metavariable)\.?\d+\b", "<mvar>", cleaned, flags=re.IGNORECASE)
    lines = [re.sub(r"[ \t]+$", "", line) for line in cleaned.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def discover_cases(cases_root: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in cases_root.glob("*/metadata.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata["_directory"] = path.parent
        cases.append(metadata)
    return sorted(cases, key=lambda item: (int(item.get("order", 999)), item["case_id"]))


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT)).replace("\\", "/")


def _command_environment(project_root: Path | None = None) -> dict[str, str]:
    ensure_elan_home()
    environment = lean_subprocess_environment(project_root)
    environment["PYTHONUTF8"] = "1"
    return environment


def _run_command(command: list[str], *, cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
        env=_command_environment(cwd),
    )


def _json_output(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    for line in reversed(process.stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return {"ok": False, "error": "command did not emit a JSON object"}


def _project_root(case: dict[str, Any]) -> Path | None:
    value = case.get("project_root")
    return (Path(case["_directory"]) / value).resolve() if value else None


def _compile(path: Path, project_root: Path | None, timeout: float) -> tuple[Any, dict[str, Any], str]:
    result = run_lean_file(path, timeout=timeout, project_root=project_root)
    normalized = normalize_diagnostics(
        result.diagnostics,
        returncode=result.returncode,
        timed_out=result.timed_out,
    )
    return result, normalized, diagnostic_key(normalized)


def _safe_remove_generated_case(path: Path, capsules_root: Path) -> None:
    path = path.resolve()
    capsules_root = capsules_root.resolve()
    if path.parent != capsules_root:
        raise ValueError(f"refusing to replace capsule outside generated root: {path.name}")
    if path.exists():
        shutil.rmtree(path)


def run_case(case: dict[str, Any], capsules_root: Path, timeout: float) -> dict[str, Any]:
    case_dir = Path(case["_directory"])
    project_root = _project_root(case)
    correct_file = case_dir / case["correct_file"]
    error_file = case_dir / case["error_file"]
    notes: list[str] = []

    setup_ok = True
    setup_elapsed_ms = 0.0
    setup_command = case.get("setup_command")
    if setup_command:
        started = time.perf_counter()
        try:
            setup = _run_command(list(setup_command), cwd=project_root or case_dir, timeout=timeout)
            setup_ok = setup.returncode == 0
        except subprocess.TimeoutExpired:
            setup_ok = False
            notes.append("environment setup timed out")
        setup_elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if not setup_ok and "environment setup timed out" not in notes:
            notes.append("environment setup failed")

    correct, correct_normalized, _ = _compile(correct_file, project_root, timeout)
    error, original_normalized, original_key = _compile(error_file, project_root, timeout)
    error_failed_as_expected = not error.ok and not error.timed_out and error.returncode is not None
    if not correct.ok:
        notes.append("correct template did not compile")
    if not error_failed_as_expected:
        notes.append("error version did not produce a normal Lean compile failure")

    capsule_dir = capsules_root / case["case_id"]
    _safe_remove_generated_case(capsule_dir, capsules_root)
    project_argument = project_root or (find_project_root(error_file) or ROOT)
    evaluation_set = str(case.get("evaluation_set", "challenge"))
    pack_command = [
        sys.executable,
        "-m",
        "leancapsule",
        "pack",
        "--project",
        _relative(project_argument),
        "--file",
        _relative(error_file),
        "--theorem",
        case["theorem"],
        "--out",
        _relative(capsule_dir),
        "--timeout",
        str(timeout),
        "--taxonomy",
        case.get("taxonomy", "Challenge"),
        "--source-kind",
        case.get("source_kind", "challenge"),
        "--license",
        "MIT",
        "--notes",
        f"LeanCapsule {evaluation_set} feasibility case: {case['case_id']}.",
    ]
    pack_started = time.perf_counter()
    try:
        pack_process = _run_command(pack_command, cwd=ROOT, timeout=max(timeout * 4, 120.0))
        pack_output = _json_output(pack_process)
    except subprocess.TimeoutExpired:
        pack_process = None
        pack_output = {"ok": False, "error": "pack timed out"}
    pack_elapsed_ms = round((time.perf_counter() - pack_started) * 1000, 1)

    manifest: dict[str, Any] = {}
    if (capsule_dir / "capsule.json").exists():
        manifest = json.loads((capsule_dir / "capsule.json").read_text(encoding="utf-8"))
    pack_ok = bool(pack_output.get("ok")) and bool(manifest)
    if not pack_ok:
        notes.append(str(pack_output.get("error", "pack failed")))

    replay_output: dict[str, Any] = {"ok": False, "error": "pack did not produce a capsule"}
    replay_elapsed_ms: float | None = None
    capsule_result = None
    capsule_normalized: dict[str, Any] = {"category": None, "errors": []}
    capsule_key: str | None = None
    public_capsule_key: str | None = None
    strict_original = strict_ordered_diagnostics(error.diagnostics, (ROOT, case_dir, Path.home()))
    strict_capsule = ""

    if pack_ok:
        with tempfile.TemporaryDirectory(prefix="tracer-capsule-challenge-") as temporary:
            isolated_capsule = Path(temporary) / case["case_id"]
            shutil.copytree(capsule_dir, isolated_capsule)
            replay_command = [
                sys.executable,
                "-m",
                "leancapsule",
                "replay",
                str(isolated_capsule),
                "--timeout",
                str(timeout),
            ]
            replay_started = time.perf_counter()
            try:
                replay_process = _run_command(replay_command, cwd=ROOT, timeout=max(timeout * 2, 60.0))
                replay_output = _json_output(replay_process)
            except subprocess.TimeoutExpired:
                replay_output = {"ok": False, "error": "replay timed out"}
            replay_elapsed_ms = round((time.perf_counter() - replay_started) * 1000, 1)

            dependency = manifest.get("environment", {}).get("dependency_project")
            capsule_project = (isolated_capsule / dependency).resolve() if dependency else isolated_capsule
            if not capsule_project.exists():
                capsule_project = isolated_capsule
            capsule_result, capsule_normalized, capsule_key = _compile(
                isolated_capsule / manifest.get("replay", {}).get("file", "Capsule.lean"),
                capsule_project,
                timeout,
            )
            public_capsule_key = redact_text(
                capsule_key,
                (ROOT, isolated_capsule, Path(temporary), Path.home()),
            )
            strict_capsule = strict_ordered_diagnostics(
                capsule_result.diagnostics,
                (ROOT, isolated_capsule, Path(temporary), Path.home()),
            )

    official_status = bool(capsule_result is not None and error.ok == capsule_result.ok)
    official_category = bool(
        capsule_result is not None and original_normalized.get("category") == capsule_normalized.get("category")
    )
    official_key = bool(capsule_result is not None and original_key == capsule_key)
    strict_preserved = bool(capsule_result is not None and strict_original == strict_capsule)
    if capsule_result is not None and not official_status:
        notes.append("capsule compilation status drifted")
    if capsule_result is not None and not official_category:
        notes.append("capsule error category drifted")
    if capsule_result is not None and not official_key:
        notes.append("capsule diagnostic_key drifted")
    if capsule_result is not None and not strict_preserved:
        notes.append("strict ordered diagnostic text drifted (challenge metric)")
    if not replay_output.get("ok"):
        notes.append("isolated replay did not satisfy the official criterion")

    extraction = manifest.get("extraction", {})
    extraction_mode = extraction.get("mode")
    if extraction_mode == "full_file_fallback":
        notes.append("theorem extraction required full-file fallback")
    return {
        "case_id": case["case_id"],
        "evaluation_set": evaluation_set,
        "taxonomy": case.get("taxonomy"),
        "source_kind": case.get("source_kind"),
        "challenge_type": case["challenge_type"],
        "correct_template_compile_ok": correct.ok,
        "error_version_failed_as_expected": error_failed_as_expected,
        "setup_ok": setup_ok,
        "setup_elapsed_ms": setup_elapsed_ms,
        "original_error_category": original_normalized.get("category"),
        "original_diagnostic_key": original_key,
        "original_diagnostic_count": len(original_normalized.get("errors", [])),
        "capsule_error_category": capsule_normalized.get("category"),
        "capsule_diagnostic_key": public_capsule_key,
        "capsule_diagnostic_count": len(capsule_normalized.get("errors", [])),
        "selection_mode": manifest.get("target", {}).get("selection_mode"),
        "extraction_mode": extraction_mode,
        "standalone": extraction_mode == "standalone",
        "full_file_fallback": extraction_mode == "full_file_fallback",
        "fallback_reason": extraction.get("fallback_reason"),
        "minimization": manifest.get("minimization"),
        "official_compile_status_preserved": official_status,
        "official_error_category_preserved": official_category,
        "official_diagnostic_key_preserved": official_key,
        "replay_success": bool(replay_output.get("ok")),
        "pack_ok": pack_ok,
        "pack_elapsed_ms": pack_elapsed_ms,
        "replay_elapsed_ms": replay_elapsed_ms,
        "strict_ordered_diagnostics_preserved": strict_preserved,
        "strict_original_diagnostics_sha256": hashlib.sha256(strict_original.encode("utf-8")).hexdigest(),
        "strict_capsule_diagnostics_sha256": hashlib.sha256(strict_capsule.encode("utf-8")).hexdigest() if capsule_result else None,
        "strict_metric_scope": (
            "Feasibility analysis only: complete ordered diagnostic text after path, location, "
            "metavariable, and trailing-whitespace normalization; not semantic equivalence and "
            "not a replacement for the official diagnostic_key."
        ),
        "notes": "; ".join(dict.fromkeys(notes)) or "No additional limitation observed.",
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)

    def count(field: str) -> int:
        return sum(bool(result.get(field)) for result in results)

    def ratio(value: int) -> float:
        return round(value / total, 4) if total else 0.0

    def average(field: str) -> float | None:
        values = [float(result[field]) for result in results if result.get(field) is not None]
        return round(mean(values), 1) if values else None

    standalone = count("standalone")
    fallback = count("full_file_fallback")
    diagnostic_preserved = count("official_diagnostic_key_preserved")
    replay = count("replay_success")
    strict = count("strict_ordered_diagnostics_preserved")
    return {
        "case_count": total,
        "standalone_count": standalone,
        "standalone_ratio": ratio(standalone),
        "full_file_fallback_count": fallback,
        "full_file_fallback_ratio": ratio(fallback),
        "official_diagnostic_key_preserved_count": diagnostic_preserved,
        "official_diagnostic_key_preserved_ratio": ratio(diagnostic_preserved),
        "replay_success_count": replay,
        "replay_success_ratio": ratio(replay),
        "strict_ordered_diagnostics_preserved_count": strict,
        "strict_ordered_diagnostics_preserved_ratio": ratio(strict),
        "average_pack_elapsed_ms": average("pack_elapsed_ms"),
        "average_replay_elapsed_ms": average("replay_elapsed_ms"),
    }


def _mark(value: Any) -> str:
    return "yes" if value else "no"


def _percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _milliseconds(value: float | None) -> str:
    return f"{value:.1f}" if value is not None else "n/a"


def render_results_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# LeanCapsule challenge pilot results",
        "",
        "Generated by `scripts/summarize_capsule_challenges.py`; do not edit measured values by hand.",
        "",
        "| case | correct | expected failure | original → capsule category | extraction | status/category/key preserved | replay | strict ordered text | pack ms | replay ms |",
        "|---|---:|---:|---|---|---|---:|---:|---:|---:|",
    ]
    for result in payload["cases"]:
        preservation = "/".join(
            _mark(result[field])
            for field in (
                "official_compile_status_preserved",
                "official_error_category_preserved",
                "official_diagnostic_key_preserved",
            )
        )
        lines.append(
            f"| `{result['case_id']}` | {_mark(result['correct_template_compile_ok'])} | "
            f"{_mark(result['error_version_failed_as_expected'])} | `{result['original_error_category']}` → "
            f"`{result['capsule_error_category']}` | `{result['extraction_mode']}` | {preservation} | "
            f"{_mark(result['replay_success'])} | {_mark(result['strict_ordered_diagnostics_preserved'])} | "
            f"{_milliseconds(result['pack_elapsed_ms'])} | {_milliseconds(result['replay_elapsed_ms'])} |"
        )
    lines.extend(
        [
            "",
            "## Detailed records",
            "",
            "| case | original diagnostic_key | capsule diagnostic_key | extraction/fallback | minimization |",
            "|---|---|---|---|---|",
        ]
    )
    for result in payload["cases"]:
        minimization = json.dumps(result.get("minimization"), ensure_ascii=False, separators=(",", ":"))
        extraction = result.get("extraction_mode") or ""
        if result.get("fallback_reason"):
            extraction += f": {result['fallback_reason']}"
        lines.append(
            f"| `{result['case_id']}` | {_cell(result['original_diagnostic_key'])} | "
            f"{_cell(result['capsule_diagnostic_key'])} | {_cell(extraction)} | {_cell(minimization)} |"
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Cases: {summary['case_count']}",
            f"- Standalone: {summary['standalone_count']}/{summary['case_count']} ({_percentage(summary['standalone_ratio'])})",
            f"- Full-file fallback: {summary['full_file_fallback_count']}/{summary['case_count']} ({_percentage(summary['full_file_fallback_ratio'])})",
            f"- Official diagnostic key preserved: {summary['official_diagnostic_key_preserved_count']}/{summary['case_count']} ({_percentage(summary['official_diagnostic_key_preserved_ratio'])})",
            f"- Replay success: {summary['replay_success_count']}/{summary['case_count']} ({_percentage(summary['replay_success_ratio'])})",
            f"- Strict ordered diagnostic text preserved: {summary['strict_ordered_diagnostics_preserved_count']}/{summary['case_count']} ({_percentage(summary['strict_ordered_diagnostics_preserved_ratio'])})",
            f"- Mean pack time: {summary['average_pack_elapsed_ms']:.1f} ms",
            f"- Mean replay time: {summary['average_replay_elapsed_ms']:.1f} ms",
            "",
            "> The strict ordered-text comparison is a challenge analysis metric only. It normalizes environment noise but neither replaces the official `diagnostic_key` nor establishes semantic equivalence.",
            "",
            "## Case notes",
            "",
        ]
    )
    for result in payload["cases"]:
        lines.append(f"- `{result['case_id']}`: {result['notes']}")
    return "\n".join(lines) + "\n"


def render_report(payload: dict[str, Any], cases: list[dict[str, Any]]) -> str:
    summary = payload["summary"]
    rendered_results = render_results_markdown(payload)
    table_start = rendered_results.index("| case |")
    table_end = rendered_results.index("\n\n## Summary", table_start)
    results_table = rendered_results[table_start:table_end].strip()
    fallback_cases = [item["case_id"] for item in payload["cases"] if item["full_file_fallback"]]
    drift_cases = [item["case_id"] for item in payload["cases"] if not item["official_diagnostic_key_preserved"]]
    replay_failures = [item["case_id"] for item in payload["cases"] if not item["replay_success"]]

    if replay_failures:
        priority = (
            "The first priority is project-local dependency encapsulation because isolated replay failed for "
            + ", ".join(f"`{case}`" for case in replay_failures)
            + ". The next priority is dependency-aware theorem extraction for same-file declarations. "
            "Diagnostic fidelity should retain a strict full-diagnostic observation alongside, but not replace, the official key."
        )
    elif fallback_cases:
        priority = (
            "No clean-replay blocker remains. Dependency-aware extraction is still an optimization opportunity because fallback was required for "
            + ", ".join(f"`{case}`" for case in fallback_cases)
            + ". The strict observation should remain an analysis layer for later diagnostic-fidelity work."
        )
    else:
        priority = "No dependency failure was observed; expand the pilot before prioritizing core changes."

    case_design_lines = []
    for case in cases:
        case_design_lines.append(
            f"- `{case['case_id']}` ({case['challenge_type']}): {case['mutation']} "
            f"Expected: {case['expected_failure']}"
        )

    return "\n".join(
        [
            "# LeanCapsule Challenge Pilot",
            "",
            "> Generated from an actual run by `scripts/summarize_capsule_challenges.py`. "
            "The measured table and counts must not be edited independently of the JSON result.",
            "",
            "## Purpose and isolation",
            "",
            "This feasibility pilot measures current theorem-based LeanCapsule behavior on four deliberately small boundary cases. "
            "It is the challenge companion to the 12-case core gate and remains separate from the public gallery release audit: fallback, diagnostic drift, and replay failure are retained as measured challenge outcomes.",
            "",
            "The combined core/challenge result is generated by `scripts/run_capsule_feasibility.py` and documented in `docs/CAPSULE_FEASIBILITY.md`.",
            "",
            "## Case design",
            "",
            *case_design_lines,
            "",
            "Every case has a compiling `Correct.lean` and an `Error.lean` differing on exactly one source line. Every error is packed with `--theorem`.",
            "",
            "## Environment and reproduction",
            "",
            f"- Git commit: `{payload['environment']['git_commit']}`",
            f"- Lean: `{payload['environment']['lean_version']}`",
            f"- Python: `{payload['environment']['python_version']}`",
            f"- Platform: `{payload['environment']['platform']}`",
            "",
            "```bash",
            "python scripts/summarize_capsule_challenges.py",
            "python -m unittest tests.test_capsule_challenges tests.test_capsule tests.test_gallery",
            "python scripts/run_ci_tests.py",
            "```",
            "",
            "The script builds the local multi-file fixture, compiles both source variants, calls the repository CLI `pack --theorem`, copies each capsule into a temporary directory, calls CLI `replay`, and performs a separate complete ordered-diagnostic comparison.",
            "",
            "## Measured results",
            "",
            results_table,
            "",
            f"Standalone: **{summary['standalone_count']}/{summary['case_count']} ({_percentage(summary['standalone_ratio'])})**. "
            f"Full-file fallback: **{summary['full_file_fallback_count']}/{summary['case_count']} ({_percentage(summary['full_file_fallback_ratio'])})**. "
            f"Official diagnostic key preserved: **{summary['official_diagnostic_key_preserved_count']}/{summary['case_count']} ({_percentage(summary['official_diagnostic_key_preserved_ratio'])})**. "
            f"Isolated replay success: **{summary['replay_success_count']}/{summary['case_count']} ({_percentage(summary['replay_success_ratio'])})**. "
            f"Mean pack/replay time: **{summary['average_pack_elapsed_ms']:.1f}/{summary['average_replay_elapsed_ms']:.1f} ms**.",
            "",
            "Fallback cases: " + (", ".join(f"`{case}`" for case in fallback_cases) if fallback_cases else "none") + ".",
            "Diagnostic-key drift cases: " + (", ".join(f"`{case}`" for case in drift_cases) if drift_cases else "none") + ".",
            "Replay failures: " + (", ".join(f"`{case}`" for case in replay_failures) if replay_failures else "none") + ".",
            "",
            "## Interpretation and next priority",
            "",
            priority,
            "",
            "The strict metric compares the complete ordered diagnostic text after normalizing paths, line/column locations, metavariable identifiers, and trailing whitespace. It is explicitly a challenge-analysis observation: text equality is not semantic equivalence, and this metric does not replace the current official status/category/`diagnostic_key` criterion.",
            "",
            "## Scope limitation",
            "",
            "This is a four-case feasibility pilot. It exposes concrete behavior in these fixtures only and does not prove general LeanCapsule feasibility, diagnostic equivalence, or robust project dependency capture.",
            "",
        ]
    )


def _version(command: list[str]) -> str:
    process = _run_command(command, cwd=ROOT, timeout=20.0)
    return (process.stdout or process.stderr).strip().splitlines()[0]


def _git_value(*arguments: str) -> str:
    process = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return process.stdout.strip() if process.returncode == 0 else "unknown"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    ensure_elan_home()
    cases = discover_cases(args.cases.resolve())
    if len(cases) != 4:
        raise SystemExit(f"expected exactly 4 challenge cases, found {len(cases)}")

    results_dir = args.results_dir.resolve()
    capsules_root = results_dir / "capsules"
    capsules_root.mkdir(parents=True, exist_ok=True)
    results = [run_case(case, capsules_root, args.timeout) for case in cases]
    payload = {
        "pilot": "leancapsule-challenge-v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "git_commit": _git_value("rev-parse", "HEAD"),
            "git_branch": _git_value("branch", "--show-current"),
            "lean_version": _version(["lean", "--version"]),
            "python_version": platform.python_version(),
            "platform": f"{platform.system()}-{platform.machine()}",
            "toolchain": (ROOT / "lean-toolchain").read_text(encoding="utf-8").strip(),
        },
        "official_criterion": "compile status, normalized category, and diagnostic_key all match",
        "strict_metric_disclaimer": (
            "Challenge analysis only. Complete ordered normalized diagnostic text is compared; "
            "this neither replaces the official criterion nor establishes semantic equivalence."
        ),
        "cases": results,
        "summary": summarize(results),
    }
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (results_dir / "summary.md").write_text(render_results_markdown(payload), encoding="utf-8")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(payload, cases), encoding="utf-8")
    print(json.dumps({"ok": True, "summary": payload["summary"]}, ensure_ascii=False))
    return 0 if all(result["correct_template_compile_ok"] and result["error_version_failed_as_expected"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
