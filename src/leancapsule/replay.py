"""回放并核验单个 LeanCapsule。"""

from __future__ import annotations

import json
from pathlib import Path

from compiler import run_lean_file, source_meta_execution_violation
from diagnostics import normalize_diagnostics

from .diagnostics_key import diagnostic_key
from .privacy import redact_value
from .schema import validate_manifest


def replay_capsule(capsule: Path, timeout: float = 180.0) -> dict:
    """编译 Capsule.lean，并返回可供脚本消费的 JSON 结果。"""

    capsule = capsule.resolve()
    manifest_path = capsule / "capsule.json"
    if not manifest_path.exists():
        return {"ok": False, "capsule": capsule.name, "error": "缺少 capsule.json"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_errors = validate_manifest(manifest)
    if schema_errors:
        return {"ok": False, "capsule": capsule.name, "error": "；".join(schema_errors)}
    source = capsule / str(manifest.get("replay", {}).get("file", "Capsule.lean"))
    if not source.exists():
        return {"ok": False, "capsule": capsule.name, "error": f"缺少回放源文件: {source.name}"}
    if source_meta_execution_violation(source.read_text(encoding="utf-8")):
        return {"ok": False, "capsule": capsule.name, "error": "回放源包含不允许的不安全声明或编译期执行入口"}
    dependency_project = manifest.get("environment", {}).get("dependency_project")
    project_root = (capsule / dependency_project).resolve() if dependency_project else capsule
    if not project_root.exists():
        project_root = capsule
    result = run_lean_file(source, timeout=timeout, project_root=project_root)
    normalized = normalize_diagnostics(result.diagnostics, returncode=result.returncode, timed_out=result.timed_out)
    actual_key = diagnostic_key(normalized)
    expected = manifest["expected"]
    same_status = bool(expected.get("compile_ok")) == result.ok
    same_category = expected.get("category") == normalized.get("category")
    same_key = expected.get("diagnostic_key") == actual_key
    ok = same_status and same_category and same_key
    public_result = {
        "ok": ok,
        "capsule": capsule.name,
        "compile_ok": result.ok,
        "returncode": result.returncode,
        "category": normalized["category"],
        "diagnostic_key": actual_key,
        "expected_diagnostic_key": expected.get("diagnostic_key"),
        "elapsed_ms": result.elapsed_ms,
        "diagnostics": normalized,
        "compiler_command": result.compiler_command,
    }
    return redact_value(public_result, (capsule, project_root, Path.home()))
