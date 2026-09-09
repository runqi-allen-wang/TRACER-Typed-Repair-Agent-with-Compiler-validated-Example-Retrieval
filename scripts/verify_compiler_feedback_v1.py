"""离线验证 Compiler Feedback v1 协议和 15 个冻结失败夹具。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from compiler import run_lean_file  # noqa: E402
from compiler_feedback import PROTOCOL_VERSION, build_feedback_record  # noqa: E402


DEFAULT_MANIFEST = ROOT / "benchmarks" / "compiler_feedback_v1" / "manifest.json"
DEFAULT_PROTOCOL = ROOT / "benchmarks" / "compiler_feedback_v1" / "protocol.json"
REQUIRED_FAMILIES = {
    "unknown_identifier": 2,
    "type_mismatch": 2,
    "unsolved_goals": 2,
    "syntax": 2,
    "typeclass": 2,
    "elaboration": 2,
    "infrastructure": 3,
}


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_frozen_manifest(path: Path = DEFAULT_MANIFEST) -> tuple[dict, dict]:
    """读取并验证版本、数量、路径和可读全文快照。"""

    path = path.resolve()
    root = path.parent
    manifest = _read_json(path)
    protocol = _read_json(root / "protocol.json")
    schema = _read_json(root / protocol.get("record_schema", ""))
    Draft202012Validator.check_schema(schema)
    if manifest.get("version") != "compiler-feedback-fixtures-v1":
        raise ValueError("夹具清单版本不匹配")
    if manifest.get("protocol_version") != PROTOCOL_VERSION or protocol.get("version") != PROTOCOL_VERSION:
        raise ValueError("夹具与协议版本不一致")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not 12 <= len(cases) <= 15:
        raise ValueError("Compiler Feedback v1 必须冻结 12～15 个失败夹具")
    ids = [case.get("id") for case in cases]
    if len(ids) != len(set(ids)) or any(not isinstance(case_id, str) for case_id in ids):
        raise ValueError("夹具 ID 缺失或重复")
    counts = Counter(case.get("family") for case in cases)
    if counts != Counter(REQUIRED_FAMILIES):
        raise ValueError(f"夹具家族覆盖不符合冻结设计: {dict(counts)}")

    for case in cases:
        file_path = (root / case["file"]).resolve()
        if not file_path.is_relative_to(root) or not file_path.is_file():
            raise ValueError(f"夹具路径非法或缺失: {case['id']}")
        snapshot_field = "source_text" if case["origin"] == "lean_compiler" else "raw_text"
        snapshot = case.get(snapshot_field)
        if not isinstance(snapshot, str) or file_path.read_text(encoding="utf-8") != snapshot:
            raise ValueError(f"夹具可读全文快照发生变化: {case['id']}")
        if not case.get("expected_contains") or not case.get("expected_signal_kinds"):
            raise ValueError(f"夹具缺少冻结断言: {case['id']}")
    protocol["_loaded_schema"] = schema
    return manifest, protocol


def verify_case(case: dict, fixture_root: Path, timeout: float) -> dict:
    """验证单个真实 Lean 或显式基础设施夹具。"""

    path = (fixture_root / case["file"]).resolve()
    if case["origin"] == "lean_compiler":
        result = run_lean_file(path, timeout=timeout, project_root=ROOT)
        if result.ok:
            raise ValueError(f"{case['id']} 应失败但 Lean 编译通过")
        if result.timed_out:
            raise ValueError(f"{case['id']} 意外超时，不能当作预期证明失败")
        record = build_feedback_record(
            case_id=case["id"],
            diagnostic_text=result.diagnostics,
            compile_ok=False,
            returncode=result.returncode,
            timed_out=False,
            origin="lean_compiler",
            roots=(ROOT,),
        )
    else:
        record = build_feedback_record(
            case_id=case["id"],
            diagnostic_text=path.read_text(encoding="utf-8"),
            compile_ok=False,
            returncode=None,
            timed_out=bool(case.get("timed_out")),
            origin=case["origin"],
            category_hint=case["expected_category"],
            roots=(ROOT,),
        )

    actual_category = record["structured"]["category"]
    if actual_category != case["expected_category"]:
        raise ValueError(
            f"{case['id']} 类别漂移: expected={case['expected_category']} actual={actual_category}"
        )
    raw_text = record["raw"]["text"]
    if case["expected_contains"].lower() not in raw_text.lower():
        raise ValueError(f"{case['id']} 原始诊断缺少冻结文本: {case['expected_contains']}")
    actual_signals = {item["kind"] for item in record["structured"]["signals"]}
    missing = set(case["expected_signal_kinds"]) - actual_signals
    if missing:
        raise ValueError(f"{case['id']} 缺少结构化信号: {sorted(missing)}")
    return record


def verify_manifest(path: Path = DEFAULT_MANIFEST, timeout: float = 30.0) -> tuple[list[dict], dict]:
    manifest, protocol = load_frozen_manifest(path)
    records = [verify_case(case, path.resolve().parent, timeout) for case in manifest["cases"]]
    validator = Draft202012Validator(protocol.pop("_loaded_schema"))
    for record in records:
        validator.validate(record)
    summary = {
        "ok": True,
        "protocol_version": protocol["version"],
        "fixtures": len(records),
        "real_lean_failures": sum(row["raw"]["origin"] == "lean_compiler" for row in records),
        "infrastructure_events": sum(row["raw"]["origin"] != "lean_compiler" for row in records),
        "categories": dict(Counter(row["structured"]["category"] for row in records)),
        "api_calls": 0,
        "existing_experiments_modified": False,
    }
    return records, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--verify-only", action="store_true", help="只验证并打印汇总，不写结果文件")
    parser.add_argument("--out", type=Path, help="可选：把本次观察记录写入新 JSONL 文件")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout 必须大于 0")
    if args.verify_only and args.out:
        parser.error("--verify-only 与 --out 不能同时使用")

    try:
        records, summary = verify_manifest(args.manifest, args.timeout)
        if args.out:
            output = args.out.resolve()
            if output.exists():
                raise ValueError(f"拒绝覆盖已有观察记录: {output}")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
                encoding="utf-8",
            )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
