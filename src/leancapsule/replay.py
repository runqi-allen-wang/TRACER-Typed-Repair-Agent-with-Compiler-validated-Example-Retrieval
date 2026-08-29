"""回放并核验单个 LeanCapsule。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from compiler import run_lake_build, run_lean_file, source_meta_execution_violation
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
    environment = manifest.get("environment", {})
    build_targets = environment.get("local_build_targets", [])
    if not isinstance(build_targets, list) or any(
        not isinstance(target, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", target)
        for target in build_targets
    ):
        return {"ok": False, "capsule": capsule.name, "error": "local_build_targets 必须是 Lean 限定名列表"}
    missing_local_files = [
        name
        for name in environment.get("local_files", [])
        if not isinstance(name, str)
        or Path(name).is_absolute()
        or ".." in Path(name).parts
        or not (project_root / name).is_file()
    ]
    if missing_local_files:
        return {
            "ok": False,
            "capsule": capsule.name,
            "stage": "dependency_validation",
            "error": "缺少或拒绝不安全的项目内依赖文件",
            "files": [str(name) for name in missing_local_files],
        }
    prebuild = None
    if build_targets:
        if not ((project_root / "lakefile.toml").is_file() or (project_root / "lakefile.lean").is_file()):
            return {
                "ok": False,
                "capsule": capsule.name,
                "stage": "dependency_build",
                "error": "缺少 Lake 配置",
            }
        prebuild = run_lake_build(project_root, build_targets, timeout=timeout)
        if not prebuild.ok:
            return redact_value(
                {
                    "ok": False,
                    "capsule": capsule.name,
                    "stage": "dependency_build",
                    "error": "项目内 Lean 依赖构建失败",
                    "elapsed_ms": prebuild.elapsed_ms,
                    "diagnostics": prebuild.diagnostics,
                    "compiler_command": prebuild.compiler_command,
                },
                (capsule, project_root, Path.home()),
            )
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
        "prebuild_required": bool(build_targets),
        "prebuild_elapsed_ms": prebuild.elapsed_ms if prebuild else 0.0,
        "prebuild_command": prebuild.compiler_command if prebuild else None,
    }
    return redact_value(public_result, (capsule, project_root, Path.home()))
