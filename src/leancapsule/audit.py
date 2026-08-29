"""对公开 capsule 执行发布前静态审计。"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from compiler import source_meta_execution_violation

from .schema import validate_json_schema, validate_manifest


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
POSIX_PRIVATE_PATH = re.compile(r"/(?:home|Users|tmp|private|var/tmp)/")
PLACEHOLDER = re.compile(r"\b(?:sorry|admit)\b", re.IGNORECASE)
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|access[_-]?token|secret|password)[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{12,}|bearer\s+[A-Za-z0-9._-]{12,}"
)
TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".md", ".lean", ".ps1", ".sh", ".toml", ".csv", ".yaml", ".yml"}


def _audit_text(path: Path, text: str) -> list[str]:
    errors: list[str] = []
    if WINDOWS_PATH.search(text) or POSIX_PRIVATE_PATH.search(text):
        errors.append(f"{path}: 包含绝对本机路径")
    if SENSITIVE_VALUE.search(text):
        errors.append(f"{path}: 疑似包含敏感凭据")
    return errors


def audit_directory(root: Path) -> dict:
    """检查布局、manifest、来源许可、内容安全与复核台账。"""

    root = root.resolve()
    errors: list[str] = []
    manifests: dict[str, dict] = {}
    # 先扫描整个发布根目录，孤立的 auth.json、日志或脚本也不能绕过审计。
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            errors.extend(_audit_text(path.relative_to(root), path.read_text(encoding="utf-8-sig", errors="replace")))
    for manifest_path in sorted(root.rglob("capsule.json")):
        capsule = manifest_path.parent
        missing = sorted(name for name in REQUIRED_FILES if not (capsule / name).exists())
        if missing:
            errors.append(f"{capsule.name}: 缺少文件 {', '.join(missing)}")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{capsule.name}: manifest 无法读取: {exc}")
            continue
        schema_errors = validate_manifest(manifest)
        schema_errors.extend(validate_json_schema(manifest))
        errors.extend(f"{capsule.name}: {error}" for error in schema_errors)
        capsule_id = manifest.get("capsule_id")
        if isinstance(capsule_id, str):
            if capsule_id in manifests:
                errors.append(f"{capsule.name}: capsule_id 重复")
            manifests[capsule_id] = manifest
        if manifest.get("taxonomy") not in TAXONOMIES:
            errors.append(f"{capsule.name}: taxonomy 不在冻结分类中")
        if manifest.get("source_kind") not in SOURCE_KINDS:
            errors.append(f"{capsule.name}: source_kind 不在冻结来源中")
        license_name = manifest.get("provenance", {}).get("license")
        if not isinstance(license_name, str) or not license_name.strip() or license_name == "未声明":
            errors.append(f"{capsule.name}: 发布案例必须声明许可")
        replay_source = capsule / manifest.get("replay", {}).get("file", "Capsule.lean")
        if not replay_source.is_file():
            errors.append(f"{capsule.name}: 回放源文件不存在")
        elif source_meta_execution_violation(replay_source.read_text(encoding="utf-8")):
            errors.append(f"{capsule.name}: 回放源包含不允许的不安全声明或编译期执行入口")
        elif manifest.get("expected", {}).get("compile_ok"):
            source = replay_source.read_text(encoding="utf-8")
            if PLACEHOLDER.search(source):
                errors.append(f"{capsule.name}: 成功案例含未完成证明占位符")

    review_path = root / "MANUAL_REVIEW.csv"
    reviewed_ids: set[str] = set()
    if not review_path.exists():
        errors.append("缺少 MANUAL_REVIEW.csv")
    else:
        with review_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            capsule_id = row.get("capsule_id", "")
            reviewed_ids.add(capsule_id)
            if row.get("review_status") != "repository_review_pass":
                errors.append(f"{capsule_id}: 发布复核尚未完成")
        if reviewed_ids != set(manifests):
            errors.append("复核台账与 gallery 的 capsule_id 不一致")

    return {
        "ok": not errors,
        "total": len(manifests),
        "reviewed": len(reviewed_ids & set(manifests)),
        "errors": errors,
    }
