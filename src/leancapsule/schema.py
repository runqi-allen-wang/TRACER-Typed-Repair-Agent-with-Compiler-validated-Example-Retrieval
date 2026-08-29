"""LeanCapsule manifest 的轻量校验与版本定义。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "leancapsule.v0.1"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "capsule_schema" / "leancapsule-v0.1.schema.json"


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """完整检查 v0.1 必需字段和主要字段类型。"""

    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest 顶层必须是对象"]
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version 必须为 leancapsule.v0.1")
    for field in ("capsule_id", "target", "environment", "expected", "provenance"):
        if field not in manifest:
            errors.append(f"缺少字段: {field}")
    if not isinstance(manifest.get("capsule_id"), str) or not manifest.get("capsule_id", "").strip():
        errors.append("capsule_id 必须是非空文本")
    target = manifest.get("target")
    if not isinstance(target, dict) or not isinstance(target.get("source_file"), str) or not target.get("source_file", "").strip():
        errors.append("target.source_file 必须存在")
    elif target.get("selection_mode") not in {"theorem", "lines"}:
        errors.append("target.selection_mode 必须为 theorem 或 lines")
    elif target.get("selection_mode") == "theorem" and not isinstance(target.get("theorem"), str):
        errors.append("theorem 选择模式必须提供 target.theorem")
    elif target.get("selection_mode") == "lines" and not isinstance(target.get("lines"), str):
        errors.append("lines 选择模式必须提供 target.lines")
    environment = manifest.get("environment")
    if not isinstance(environment, dict):
        errors.append("environment 必须是对象")
    elif "local_build_targets" in environment and (
        not isinstance(environment["local_build_targets"], list)
        or not all(isinstance(item, str) for item in environment["local_build_targets"])
    ):
        errors.append("environment.local_build_targets 必须是文本列表")
    expected = manifest.get("expected")
    if not isinstance(expected, dict) or not expected.get("category"):
        errors.append("expected.category 必须存在")
    if not isinstance(expected, dict) or not isinstance(expected.get("diagnostic_key"), str):
        errors.append("expected.diagnostic_key 必须是文本")
    if not isinstance(expected, dict) or not isinstance(expected.get("compile_ok"), bool):
        errors.append("expected.compile_ok 必须是布尔值")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("provenance 必须是对象")
    elif not isinstance(provenance.get("license"), str):
        errors.append("provenance.license 必须是文本")
    replay = manifest.get("replay")
    if not isinstance(replay, dict) or not isinstance(replay.get("file"), str):
        errors.append("replay.file 必须存在")
    return errors


def validate_json_schema(manifest: dict[str, Any], schema_path: Path = DEFAULT_SCHEMA_PATH) -> list[str]:
    """使用发布的 JSON Schema 检查 manifest，并返回可读错误。"""

    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return ["缺少 jsonschema 依赖，请先安装 requirements.txt"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [f"JSON Schema: {error.message}" for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.path))]
