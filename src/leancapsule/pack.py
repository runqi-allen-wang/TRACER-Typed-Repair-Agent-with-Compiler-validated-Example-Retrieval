"""把 Lean 文件打包为可回放的 capsule。"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from compiler import declaration_scope, find_project_root, run_lean_file, source_meta_execution_violation
from diagnostics import normalize_diagnostics

from .diagnostics_key import diagnostic_key
from .extract import extract_theorem
from .minimize import minimize_imports
from .privacy import redact_text
from .schema import SCHEMA_VERSION, validate_manifest


def _copy_if_present(source: Path, destination: Path) -> bool:
    if source.exists():
        shutil.copy2(source, destination / source.name)
        return True
    return False


def _parse_lines(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+):(\d+)", value.strip())
    if not match or int(match.group(1)) < 1 or int(match.group(2)) < int(match.group(1)):
        raise ValueError("--lines 必须是 START:END，且行号从 1 开始")
    return int(match.group(1)), int(match.group(2))


def _read_toolchain(root: Path | None) -> str | None:
    if root is None:
        return None
    path = root / "lean-toolchain"
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def _copy_local_imports(source: str, project_root: Path | None, destination: Path) -> list[str]:
    """复制项目内能直接定位的 import 源文件，避免 fallback 丢失局部模块。"""

    if project_root is None:
        return []
    copied: list[str] = []
    pending = [line.strip()[len("import "):].strip() for line in source.splitlines() if line.strip().startswith("import ")]
    seen: set[str] = set()
    while pending and len(copied) < 32:
        module = pending.pop(0)
        if module in seen or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", module):
            continue
        seen.add(module)
        relative = Path(*module.split("."))
        candidates = [project_root / (str(relative) + ".lean"), project_root / "lean_project" / (str(relative) + ".lean")]
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        if found is None:
            continue
        relative_name = found.relative_to(project_root)
        target = destination / relative_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(found, target)
        copied.append(str(relative_name).replace("\\", "/"))
        olean = found.with_suffix(".olean")
        if olean.exists():
            shutil.copy2(olean, target.with_suffix(".olean"))
            copied.append(str(relative_name.with_suffix(".olean")).replace("\\", "/"))
        imported = found.read_text(encoding="utf-8")
        pending.extend(line.strip()[len("import "):].strip() for line in imported.splitlines() if line.strip().startswith("import "))
    return copied


def _write_scripts(out: Path) -> None:
    (out / "replay.sh").write_text(
        "#!/usr/bin/env sh\nset -eu\n"
        "SCRIPT_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "REPOSITORY_ROOT=\"$SCRIPT_DIR\"\n"
        "while [ \"$REPOSITORY_ROOT\" != \"/\" ] && [ ! -f \"$REPOSITORY_ROOT/leancapsule/__main__.py\" ]; do REPOSITORY_ROOT=$(dirname -- \"$REPOSITORY_ROOT\"); done\n"
        "if [ -f \"$REPOSITORY_ROOT/leancapsule/__main__.py\" ]; then cd \"$REPOSITORY_ROOT\"; fi\n"
        "python -m leancapsule replay \"$SCRIPT_DIR\"\n",
        encoding="utf-8",
    )
    (out / "replay.ps1").write_text(
        "[CmdletBinding()] param()\n"
        "$ErrorActionPreference = 'Stop'\n"
        "$CapsuleRoot = Split-Path -Parent $MyInvocation.MyCommand.Path\n"
        "$RepositoryRoot = $CapsuleRoot\n"
        "while ($RepositoryRoot -and -not (Test-Path -LiteralPath (Join-Path $RepositoryRoot 'leancapsule\\__main__.py'))) {\n"
        "  $Parent = Split-Path -Parent $RepositoryRoot\n"
        "  if ($Parent -eq $RepositoryRoot) { $RepositoryRoot = $null } else { $RepositoryRoot = $Parent }\n"
        "}\n"
        "if ($RepositoryRoot) { Push-Location $RepositoryRoot }\n"
        "try { python -m leancapsule replay $CapsuleRoot; exit $LASTEXITCODE } finally { if ($RepositoryRoot) { Pop-Location } }\n",
        encoding="utf-8-sig",
    )


def _public_diagnostics(text: str, source_file: Path, project_root: Path | None, capsule_root: Path) -> str:
    """保留原始编译器消息，同时移除不能进入公开工件的本机路径。"""

    cleaned = text.replace(str(source_file), source_file.name)
    cleaned = cleaned.replace(str(capsule_root), "<capsule>")
    if project_root:
        cleaned = cleaned.replace(str(project_root), "<project>")
    cleaned = re.sub(r"(?m)^[A-Za-z]:[\\/].+?(?=:\d+:\d+:\s*(?:error|warning))", source_file.name, cleaned)
    cleaned = re.sub(r"(?m)^/(?:home|Users|tmp|private|var/tmp)/.+?(?=:\d+:\d+:\s*(?:error|warning))", source_file.name, cleaned)
    cleaned = re.sub(r"(?mi)^[A-Za-z]:[\\/].*$", "<search-path>", cleaned)
    cleaned = re.sub(r"(?m)^/(?:home|Users|tmp|private|var/tmp)/.*$", "<search-path>", cleaned)
    return redact_text(cleaned, tuple(path for path in (source_file.parent, project_root, capsule_root) if path))


def pack_capsule(
    project: Path,
    source_file: Path,
    out: Path,
    *,
    theorem: str | None = None,
    lines: str | None = None,
    timeout: float = 60.0,
    minimize: bool = True,
    taxonomy: str | None = None,
    source_kind: str | None = None,
    license_name: str = "未声明",
    source_url: str | None = None,
    notes: str = "由 pack 命令生成，请人工补充来源。",
) -> dict:
    """生成 capsule，并在可行时验证 standalone 与 import 最小化。"""

    source_file = source_file.resolve()
    project = project.resolve()
    if not source_file.exists():
        raise FileNotFoundError(source_file)
    if bool(theorem) == bool(lines):
        raise ValueError("必须且只能指定 --theorem 或 --lines")
    source = source_file.read_text(encoding="utf-8")
    if source_meta_execution_violation(source):
        raise ValueError("源文件包含不允许进入公开 Capsule 的不安全声明或编译期执行入口")
    if theorem:
        declaration_scope(source, theorem)
        selection_mode = "theorem"
        selection = {"theorem": theorem}
    else:
        start, end = _parse_lines(lines or "")
        selected = source.splitlines()
        if end > len(selected):
            raise ValueError("--lines 超出文件行数")
        selection_mode = "lines"
        selection = {"lines": f"{start}:{end}"}

    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        source_file.relative_to(project)
        source_is_inside_project = True
    except ValueError:
        source_is_inside_project = False
    lake_root = (find_project_root(source_file) if source_is_inside_project else None) or find_project_root(project)
    if lake_root is None and ((project / "lakefile.toml").exists() or (project / "lakefile.lean").exists()):
        lake_root = project
    copied_manifest = _copy_if_present(lake_root / "lake-manifest.json", out) if lake_root else False
    copied_lakefile = _copy_if_present(lake_root / "lakefile.toml", out) if lake_root else False
    if lake_root:
        _copy_if_present(lake_root / "lakefile.lean", out)
        _copy_if_present(lake_root / "lean-toolchain", out)
    local_files = _copy_local_imports(source, lake_root, out)
    dependency_project = None
    if lake_root and (lake_root / "lakefile.lean").exists():
        dependency_project = os.path.relpath(lake_root, out).replace("\\", "/")

    original_result = run_lean_file(source_file, timeout=timeout, project_root=lake_root)
    normalized = normalize_diagnostics(
        original_result.diagnostics,
        returncode=original_result.returncode,
        timed_out=original_result.timed_out,
    )
    key = diagnostic_key(normalized)
    capsule_source = out / "Capsule.lean"
    capsule_source.write_text(source, encoding="utf-8")
    capsule_mode = "full_file_fallback"
    fallback_reason = "目标依赖完整文件上下文，或 standalone 编译结果与原始诊断不一致"
    minimization: dict = {
        "mode": "full_file_fallback",
        "reason": "保留完整源文件以保证上下文不丢失",
        "compile_attempts": 1,
    }
    if theorem:
        standalone = extract_theorem(source, theorem)
        capsule_source.write_text(standalone, encoding="utf-8")
        standalone_result = run_lean_file(capsule_source, timeout=timeout, project_root=out)
        standalone_diagnostic = normalize_diagnostics(
            standalone_result.diagnostics,
            returncode=standalone_result.returncode,
            timed_out=standalone_result.timed_out,
        )
        standalone_key = diagnostic_key(standalone_diagnostic)
        if standalone_result.ok == original_result.ok and standalone_key == key:
            capsule_mode = "standalone"
            selected_source = standalone
            minimization = {
                "mode": "standalone",
                "original_imports": sum(1 for line in standalone.splitlines() if re.match(r"^\s*import\s+", line)),
                "retained_imports": sum(1 for line in standalone.splitlines() if re.match(r"^\s*import\s+", line)),
                "compile_attempts": 1,
            }
            if minimize:
                def trial(candidate: str) -> tuple[bool, str]:
                    capsule_source.write_text(candidate, encoding="utf-8")
                    trial_result = run_lean_file(capsule_source, timeout=timeout, project_root=out)
                    trial_diagnostic = normalize_diagnostics(
                        trial_result.diagnostics,
                        returncode=trial_result.returncode,
                        timed_out=trial_result.timed_out,
                    )
                    return trial_result.ok == original_result.ok, diagnostic_key(trial_diagnostic)

                selected_source, minimization = minimize_imports(standalone, trial, key)
                capsule_source.write_text(selected_source, encoding="utf-8")
                minimization["mode"] = "standalone_verified_greedy_imports"
        else:
            capsule_source.write_text(source, encoding="utf-8")
    else:
        capsule_source.write_text(source, encoding="utf-8")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "capsule_id": out.name,
        "target": {"source_file": source_file.name, **selection, "selection_mode": selection_mode},
        "environment": {
            "lean_toolchain": _read_toolchain(lake_root),
            "lake_manifest_present": copied_manifest,
            "lakefile_present": copied_lakefile,
            "local_files": local_files,
            "dependency_project": dependency_project,
        },
        "expected": {
            "compile_ok": original_result.ok,
            "returncode": original_result.returncode,
            "category": normalized["category"],
            "diagnostic_key": key,
            "summary": normalized["summary"],
        },
        "extraction": {"mode": capsule_mode, "fallback_reason": None if capsule_mode == "standalone" else fallback_reason},
        "minimization": minimization,
        "taxonomy": taxonomy,
        "source_kind": source_kind,
        "provenance": {"license": license_name, "source_url": source_url, "notes": notes},
        "replay": {"file": "Capsule.lean", "command": "python -m leancapsule replay ."},
    }
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("manifest 校验失败: " + "; ".join(errors))
    (out / "capsule.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    public_diagnostics = _public_diagnostics(original_result.diagnostics, source_file, lake_root, out)
    (out / "expected-diagnostic.txt").write_text(public_diagnostics or "Lean 编译通过。\n", encoding="utf-8")
    (out / "README.md").write_text(
        f"# {out.name}\n\n"
        f"目标文件：`{source_file.name}`\n\n"
        f"诊断类别：`{normalized['category']}`\n\n"
        "在安装相同 Lean 工具链后运行 `python -m leancapsule replay .`。\n",
        encoding="utf-8",
    )
    _write_scripts(out)
    return manifest
