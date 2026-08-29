"""生成 capsule gallery 索引并检查覆盖要求。"""

from __future__ import annotations

import json
import csv
from collections import Counter
from pathlib import Path

from .schema import validate_manifest


def write_gallery_reports(index: dict, json_out: Path, csv_out: Path | None = None, markdown_out: Path | None = None) -> None:
    """同时写出 JSON、CSV 和面向读者的 Markdown 索引。"""

    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    csv_out = csv_out or json_out.with_suffix(".csv")
    markdown_out = markdown_out or json_out.with_suffix(".md")
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["capsule_id", "path", "taxonomy", "source_kind", "category", "extraction_mode"])
        writer.writeheader()
        writer.writerows(index.get("capsules", []))
    lines = [
        "# LeanCapsule Gallery",
        "",
        f"- 总数：{index.get('total', 0)}",
        f"- 状态：{'通过' if index.get('ok') else '未通过'}",
        "",
        "| capsule | 来源 | 分类 | 诊断类别 | 抽取模式 |",
        "|---|---|---|---|---|",
    ]
    for entry in index.get("capsules", []):
        lines.append(
            f"| `{entry['capsule_id']}` | `{entry.get('source_kind') or ''}` | "
            f"{entry.get('taxonomy') or ''} | `{entry['category']}` | `{entry.get('extraction_mode') or ''}` |"
        )
    markdown_out.parent.mkdir(parents=True, exist_ok=True)
    markdown_out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_gallery_index(root: Path) -> dict:
    """汇总所有 manifest，检查总数、错误家族和来源覆盖。"""

    entries: list[dict] = []
    errors: list[str] = []
    for path in sorted(root.rglob("capsule.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        schema_errors = validate_manifest(manifest)
        if schema_errors:
            errors.extend(f"{path.parent}: {error}" for error in schema_errors)
            continue
        entries.append(
            {
                "capsule_id": manifest["capsule_id"],
                "path": str(path.parent.relative_to(root)).replace("\\", "/"),
                "taxonomy": manifest.get("taxonomy"),
                "source_kind": manifest.get("source_kind"),
                "category": manifest["expected"]["category"],
                "extraction_mode": manifest.get("extraction", {}).get("mode"),
            }
        )
    taxonomy_counts = Counter(entry.get("taxonomy") for entry in entries if entry.get("taxonomy"))
    source_counts = Counter(entry.get("source_kind") for entry in entries if entry.get("source_kind"))
    requirements = {
        "minimum_total": len(entries) >= 12,
        "minimum_taxonomy": all(taxonomy_counts.get(name, 0) >= 3 for name in ("Name / import", "Type / application", "Elaboration / instance", "Goal / scope")),
        "minimum_sources": all(source_counts.get(name, 0) >= 4 for name in ("std", "mathlib", "project_local")),
    }
    return {
        "ok": not errors and all(requirements.values()),
        "total": len(entries),
        "taxonomy_counts": dict(taxonomy_counts),
        "source_counts": dict(source_counts),
        "requirements": requirements,
        "errors": errors,
        "capsules": entries,
    }
