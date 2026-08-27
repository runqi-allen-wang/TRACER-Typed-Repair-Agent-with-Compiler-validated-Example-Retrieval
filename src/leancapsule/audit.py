"""对公开 capsule 执行发布前静态审计。"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from compiler import source_meta_execution_violation

from .paths import resolve_capsule_file, resolve_dependency_project
from .schema import validate_full_manifest


REQUIRED_FILES = {
    "Capsule.lean",
    "capsule.json",
    "expected-diagnostic.txt",
    "README.md",
    "replay.ps1",
    "replay.sh",
    "lean-toolchain",
}
TAXONOMIES = {"Name / import", "Type / application", "Elaboration / instance", "Goal / scope"}
SOURCE_KINDS = {"std", "mathlib", "project_local"}
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
UNC_PATH = re.compile(r"\\\\[^\\\s]+\\[^\\\s]+")
POSIX_PRIVATE_PATH = re.compile(r"(?<![:A-Za-z0-9])/(?:home|Users|tmp|private|var/tmp|root|workspace|workspaces|opt|mnt|Volumes)/")
PLACEHOLDER = re.compile(r"\b(?:sorryAx|sorry|admit)\b", re.IGNORECASE)
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:[\"']?(?:[A-Z0-9_]*(?:API[_-]?KEY|ACCESS[_-]?TOKEN|REFRESH[_-]?TOKEN|ID[_-]?TOKEN)"
    r"|AUTHORIZATION)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{12,}"
    r"|bearer\s+[A-Za-z0-9._~+/-]{12,}|(?:sk|rk|pk)-(?:proj-)?[A-Za-z0-9_-]{16,})"
)
TEXT_SUFFIXES = {"", ".cfg", ".conf", ".csv", ".env", ".ini", ".json", ".lean", ".lock", ".md", ".ps1", ".sh", ".toml", ".txt", ".yaml", ".yml"}
REVIEW_FIELDS = ("replay_pass", "semantic_match", "provenance_review", "sensitive_content_review")


def _audit_text(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    if WINDOWS_PATH.search(text) or UNC_PATH.search(text) or POSIX_PRIVATE_PATH.search(text):
        errors.append(f"{path}: 包含绝对本机路径")
    if SENSITIVE_VALUE.search(text):
        errors.append(f"{path}: 疑似包含敏感凭据")
    return errors


def audit_directory(root: Path) -> dict:
    """检查布局、manifest、来源许可、内容安全与复核台账。"""

    root = root.resolve()
    errors: list[str] = []
    manifests: dict[str, dict] = {}
    if not root.is_dir():
        return {"ok": False, "total": 0, "reviewed": 0, "errors": ["审计目录不存在"]}
    manifest_paths = sorted(root.rglob("capsule.json"))
    if not manifest_paths:
        errors.append("未找到 capsule.json")
    for manifest_path in manifest_paths:
        capsule = manifest_path.parent
        missing = sorted(name for name in REQUIRED_FILES if not (capsule / name).exists())
        if missing:
            errors.append(f"{capsule.name}: 缺少文件 {', '.join(missing)}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{capsule.name}: manifest 无法读取: {exc}")
            continue
        schema_errors = validate_full_manifest(manifest)
        errors.extend(f"{capsule.name}: {error}" for error in schema_errors)
        if not isinstance(manifest, dict):
            continue
        capsule_id = manifest.get("capsule_id")
        if isinstance(capsule_id, str):
            if capsule_id in manifests:
                errors.append(f"{capsule.name}: capsule_id 重复")
            manifests[capsule_id] = manifest
            if capsule_id != capsule.name:
                errors.append(f"{capsule.name}: capsule_id 必须与目录名一致")
        if manifest.get("taxonomy") not in TAXONOMIES:
            errors.append(f"{capsule.name}: taxonomy 不在冻结分类中")
        if manifest.get("source_kind") not in SOURCE_KINDS:
            errors.append(f"{capsule.name}: source_kind 不在冻结来源中")
        provenance = manifest.get("provenance") if isinstance(manifest.get("provenance"), dict) else {}
        license_name = provenance.get("license")
        if not isinstance(license_name, str) or not license_name.strip() or license_name == "未声明":
            errors.append(f"{capsule.name}: 发布案例必须声明许可")

        environment = manifest.get("environment") if isinstance(manifest.get("environment"), dict) else {}
        actual_lakefile = (capsule / "lakefile.toml").is_file() or (capsule / "lakefile.lean").is_file()
        actual_manifest = (capsule / "lake-manifest.json").is_file()
        if environment.get("lakefile_present") is not actual_lakefile:
            errors.append(f"{capsule.name}: environment.lakefile_present 与文件不一致")
        if environment.get("lake_manifest_present") is not actual_manifest:
            errors.append(f"{capsule.name}: environment.lake_manifest_present 与文件不一致")
        toolchain_file = capsule / "lean-toolchain"
        if toolchain_file.is_file():
            actual_toolchain = toolchain_file.read_text(encoding="utf-8").strip()
            if environment.get("lean_toolchain") != actual_toolchain:
                errors.append(f"{capsule.name}: environment.lean_toolchain 与文件不一致")
        local_files = environment.get("local_files", [])
        if not isinstance(local_files, list):
            errors.append(f"{capsule.name}: environment.local_files 必须是列表")
        else:
            for local_file in local_files:
                if not isinstance(local_file, str):
                    errors.append(f"{capsule.name}: environment.local_files 必须只含文本路径")
                    continue
                try:
                    resolved_local = resolve_capsule_file(capsule, local_file, "environment.local_files")
                except ValueError as exc:
                    errors.append(f"{capsule.name}: {exc}")
                else:
                    if not resolved_local.is_file():
                        errors.append(f"{capsule.name}: local file 不存在: {local_file}")
        try:
            dependency_project = resolve_dependency_project(capsule, environment.get("dependency_project"))
        except ValueError as exc:
            errors.append(f"{capsule.name}: {exc}")
        else:
            if not dependency_project.is_dir():
                errors.append(f"{capsule.name}: 依赖项目目录不存在")
            elif dependency_project != capsule and not ((dependency_project / "lakefile.toml").is_file() or (dependency_project / "lakefile.lean").is_file()):
                errors.append(f"{capsule.name}: 依赖项目缺少 lakefile")

        replay = manifest.get("replay") if isinstance(manifest.get("replay"), dict) else {}
        try:
            replay_source = resolve_capsule_file(capsule, replay.get("file", ""))
        except ValueError as exc:
            errors.append(f"{capsule.name}: {exc}")
        else:
            if not replay_source.is_file():
                errors.append(f"{capsule.name}: 回放源文件不存在")
            elif source_meta_execution_violation(replay_source.read_text(encoding="utf-8")):
                errors.append(f"{capsule.name}: 回放源包含不允许的不安全声明或编译期执行入口")
            elif manifest.get("expected", {}).get("compile_ok"):
                source = replay_source.read_text(encoding="utf-8")
                if PLACEHOLDER.search(source):
                    errors.append(f"{capsule.name}: 成功案例含未完成证明占位符")

    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in {".env", ".npmrc", ".pypirc"}:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(f"{path.relative_to(root)}: 无法读取: {exc}")
            else:
                errors.extend(_audit_text(path.relative_to(root), text))

    review_path = root / "MANUAL_REVIEW.csv"
    reviewed_ids: set[str] = set()
    if not review_path.exists():
        errors.append("缺少 MANUAL_REVIEW.csv")
    else:
        try:
            with review_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, csv.Error) as exc:
            rows = []
            errors.append(f"MANUAL_REVIEW.csv 无法读取: {exc}")
        for row in rows:
            capsule_id = str(row.get("capsule_id") or "").strip()
            if capsule_id in reviewed_ids:
                errors.append(f"{capsule_id}: 复核台账重复")
            reviewed_ids.add(capsule_id)
            failed_fields = [field for field in REVIEW_FIELDS if str(row.get(field) or "").strip().lower() != "true"]
            if failed_fields:
                errors.append(f"{capsule_id}: 复核字段未通过: {', '.join(failed_fields)}")
            if str(row.get("review_status") or "").strip() != "repository_review_pass":
                errors.append(f"{capsule_id}: 发布复核尚未完成")
        if reviewed_ids != set(manifests):
            errors.append("复核台账与 gallery 的 capsule_id 不一致")

    return {
        "ok": not errors,
        "total": len(manifests),
        "reviewed": len(reviewed_ids & set(manifests)),
        "errors": errors,
    }
