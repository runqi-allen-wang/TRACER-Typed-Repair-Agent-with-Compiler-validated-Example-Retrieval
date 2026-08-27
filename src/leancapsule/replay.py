"""回放并核验单个 LeanCapsule。"""

from __future__ import annotations

import copy
import json
import re
import tempfile
from pathlib import Path

from compiler import run_lean_file, source_meta_execution_violation
from diagnostics import normalize_diagnostics

from .diagnostics_key import diagnostic_key
from .paths import resolve_capsule_file, resolve_dependency_project
from .schema import validate_full_manifest


WINDOWS_LOCATION = re.compile(r"(?i)[A-Z]:[\\/][^\r\n]+?(?=:\d+:\d+)")
POSIX_LOCATION = re.compile(r"/(?:[^/\s:]+/)+[^/\s:]+(?=:\d+:\d+)")


def _redact_text(text: str, capsule: Path, source: Path, project_root: Path) -> str:
    replacements = {
        str(source.resolve()): f"<capsule>/{source.name}",
        str(capsule.resolve()): "<capsule>",
        str(Path(tempfile.gettempdir()).resolve()): "<temp>",
        str(Path.home().resolve()): "<home>",
    }
    if project_root.resolve() != capsule.resolve():
        replacements[str(project_root.resolve())] = "<dependency-project>"
    cleaned = text
    for original, replacement in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        cleaned = re.sub(re.escape(original), replacement, cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace(original.replace("\\", "/"), replacement)
    cleaned = WINDOWS_LOCATION.sub("<path>", cleaned)
    cleaned = POSIX_LOCATION.sub("<path>", cleaned)
    return cleaned


def _public_diagnostics(diagnostics: dict, capsule: Path, source: Path, project_root: Path) -> dict:
    public = copy.deepcopy(diagnostics)
    for field in ("summary", "feedback"):
        if isinstance(public.get(field), str):
            public[field] = _redact_text(public[field], capsule, source, project_root)
    for error in public.get("errors", []):
        if not isinstance(error, dict):
            continue
        for field in ("location", "message"):
            if isinstance(error.get(field), str):
                error[field] = _redact_text(error[field], capsule, source, project_root)
    return public


def _public_command(command: list[str] | None, capsule: Path, source: Path, project_root: Path) -> list[str] | None:
    if command is None:
        return None
    return [_redact_text(str(argument), capsule, source, project_root) for argument in command]


def replay_capsule(capsule: Path, timeout: float = 180.0) -> dict:
    """编译 Capsule.lean，并返回可供脚本消费的 JSON 结果。"""

    capsule = capsule.resolve()
    manifest_path = capsule / "capsule.json"
    if not capsule.is_dir():
        return {"ok": False, "capsule": capsule.name, "error": "capsule 目录不存在"}
    if not manifest_path.is_file():
        return {"ok": False, "capsule": capsule.name, "error": "缺少 capsule.json"}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "capsule": capsule.name, "error": f"manifest 无法读取: {exc}"}
    schema_errors = validate_full_manifest(manifest)
    if schema_errors:
        return {"ok": False, "capsule": capsule.name, "error": "；".join(schema_errors)}
    try:
        source = resolve_capsule_file(capsule, manifest["replay"]["file"])
        project_root = resolve_dependency_project(capsule, manifest["environment"].get("dependency_project"))
    except ValueError as exc:
        return {"ok": False, "capsule": capsule.name, "error": str(exc)}
    if not source.is_file():
        return {"ok": False, "capsule": capsule.name, "error": f"缺少回放源文件: {source.name}"}
    if source_meta_execution_violation(source.read_text(encoding="utf-8")):
        return {"ok": False, "capsule": capsule.name, "error": "回放源包含不允许的不安全声明或编译期执行入口"}
    if not project_root.is_dir():
        return {"ok": False, "capsule": capsule.name, "error": "依赖项目目录不存在"}
    if project_root != capsule and not ((project_root / "lakefile.toml").is_file() or (project_root / "lakefile.lean").is_file()):
        return {"ok": False, "capsule": capsule.name, "error": "依赖项目缺少 lakefile"}
    result = run_lean_file(source, timeout=timeout, project_root=project_root)
    normalized = normalize_diagnostics(result.diagnostics, returncode=result.returncode, timed_out=result.timed_out)
    actual_key = diagnostic_key(normalized)
    expected = manifest["expected"]
    same_status = bool(expected.get("compile_ok")) == result.ok
    same_category = expected.get("category") == normalized.get("category")
    same_key = expected.get("diagnostic_key") == actual_key
    ok = same_status and same_category and same_key
    return {
        "ok": ok,
        "capsule": capsule.name,
        "compile_ok": result.ok,
        "returncode": result.returncode,
        "category": normalized["category"],
        "diagnostic_key": actual_key,
        "expected_diagnostic_key": expected.get("diagnostic_key"),
        "elapsed_ms": result.elapsed_ms,
        "diagnostics": _public_diagnostics(normalized, capsule, source, project_root),
        "compiler_command": _public_command(result.compiler_command, capsule, source, project_root),
    }
