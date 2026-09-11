"""审计 Feedback Study v1 跨模型比较发布目录。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


FORMAT = "tracer-feedback-cross-model-comparison-v1"
WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
PRIVATE_POSIX_PATH = re.compile(r"/(?:home|Users|tmp|private|var/tmp)/")
SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|secret|password)"
    r"[\"']?\s*[:=]\s*[\"']?[^\s\"',}]{12,}|bearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\b(?:sk|yi)-[A-Za-z0-9._~+/=-]{12,}"
)


def audit_comparison(root: Path) -> dict:
    root = root.resolve()
    errors: list[str] = []
    required = {"README.md", "comparison.json", "by_representation.csv", "MANIFEST.json"}
    missing = sorted(name for name in required if not (root / name).is_file())
    if missing:
        return {"ok": False, "errors": ["缺少比较文件: " + ", ".join(missing)]}
    try:
        report = json.loads((root / "comparison.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        with (root / "by_representation.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"ok": False, "errors": [f"比较文件无法读取: {exc}"]}
    if report.get("format") != FORMAT or manifest.get("format") != FORMAT:
        errors.append("跨模型比较格式不匹配")
    if report.get("ok") is not True or report.get("matched_tasks") != 216:
        errors.append("跨模型报告未通过完整 216 任务门禁")
    by_representation = report.get("by_representation", [])
    if (
        len(by_representation) != 3
        or {row.get("representation") for row in by_representation}
        != {"raw", "normalized", "structured"}
        or any(row.get("matched_tasks") != 72 for row in by_representation)
    ):
        errors.append("跨模型表示汇总未形成三个 72 任务配对")
    contrasts = report.get("contrast_direction_consistency", [])
    if len(contrasts) != 3 or any(row.get("matched_problem_repeats") != 72 for row in contrasts):
        errors.append("跨模型表示差方向汇总不完整")
    if len(rows) != 3 or {row.get("representation") for row in rows} != {"raw", "normalized", "structured"}:
        errors.append("by_representation.csv 与三表示设计不一致")
    baseline_model = report.get("baseline", {}).get("model", {})
    replication_model = report.get("replication", {}).get("model", {})
    if (
        baseline_model.get("api_url") == replication_model.get("api_url")
        and baseline_model.get("model") == replication_model.get("model")
    ):
        errors.append("跨模型报告实际使用了相同模型身份")

    listed = {
        str(item.get("path")): item.get("size_bytes")
        for item in manifest.get("files", [])
        if isinstance(item, dict)
    }
    actual = {
        path.relative_to(root).as_posix(): path.stat().st_size
        for path in sorted(root.iterdir())
        if path.is_file() and path.name != "MANIFEST.json"
    }
    if listed != actual or manifest.get("inventory_method") != "relative path and byte size":
        errors.append("跨模型比较文件清单或字节数不一致")
    for path in sorted(root.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if WINDOWS_PATH.search(text) or PRIVATE_POSIX_PATH.search(text):
            errors.append(f"{path.name}: 包含本机绝对路径")
        if SECRET_VALUE.search(text):
            errors.append(f"{path.name}: 疑似包含认证值")
    return {"ok": not errors, "matched_tasks": report.get("matched_tasks", 0), "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path)
    args = parser.parse_args()
    result = audit_comparison(args.comparison)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
