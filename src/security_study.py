"""离线计算 SP 安全回归的误放行、误拒绝与门禁位置。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from compiler import candidate_safety_finding, compile_candidate


PROTOCOL_VERSION = "tracer-sp-evaluation-v2"


def wilson_interval(successes: int, total: int, z: float = 1.96) -> dict[str, float | int | None]:
    """计算二项比例的 Wilson 区间；小样本时避免把 0 次观察写成零风险。"""

    if total <= 0:
        return {"count": successes, "total": total, "rate": None, "low": None, "high": None}
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return {
        "count": successes,
        "total": total,
        "rate": rate,
        "low": max(0.0, center - margin),
        "high": min(1.0, center + margin),
    }


def evaluate_suite(root: Path) -> dict:
    manifest = json.loads((root / "benchmarks/security/manifest.json").read_text(encoding="utf-8"))
    threat_model = json.loads((root / "benchmarks/security/threat_model.json").read_text(encoding="utf-8"))
    case_ids = [case["id"] for case in manifest]
    if case_ids != threat_model["cases"]:
        raise ValueError("威胁模型与 SP 清单不一致")

    cases = []
    for case in manifest:
        source = (root / case["file"]).read_text(encoding="utf-8")
        finding = candidate_safety_finding(source)
        cases.append({
            "id": case["id"],
            "risk": case["risk"],
            "expected_layer": case["expected_layer"],
            "expected_detector": case["expected_detector"],
            "observed_detector": finding["detector"] if finding else None,
            "detector_matches": bool(finding and finding["detector"] == case["expected_detector"]),
            "rejected_before_compile": finding is not None,
            "observed_category": "unsafe_candidate" if finding else "allowed",
            "compile_invoked": False,
        })

    compilation = threat_model["control_compilation"]
    target_path = root / compilation["source_file"]
    target_source = target_path.read_text(encoding="utf-8")
    controls = []
    for control in threat_model["controls"]:
        source = (root / control["file"]).read_text(encoding="utf-8")
        finding = candidate_safety_finding(source)
        compile_invoked = finding is None
        compile_ok = False
        if compile_invoked:
            compile_ok = compile_candidate(
                target_path,
                target_source,
                source,
                compilation["theorem"],
                timeout=float(compilation["timeout_seconds"]),
            ).ok
        controls.append({
            "id": control["id"],
            "allowed": finding is None,
            "observed_category": "allowed" if finding is None else "unsafe_candidate",
            "observed_detector": finding["detector"] if finding else None,
            "compile_invoked": compile_invoked,
            "compile_ok": compile_ok if compile_invoked else None,
        })

    false_acceptances = [item["id"] for item in cases if not item["rejected_before_compile"]]
    false_rejections = [item["id"] for item in controls if not item["allowed"]]
    compiled_before_rejection = [item["id"] for item in cases if item["compile_invoked"]]
    detector_mismatches = [item["id"] for item in cases if not item["detector_matches"]]
    control_compile_failures = [
        item["id"] for item in controls if item["compile_invoked"] and not item["compile_ok"]
    ]
    risk_coverage: dict[str, int] = {}
    detector_coverage: dict[str, int] = {}
    for case in cases:
        risk_coverage[case["risk"]] = risk_coverage.get(case["risk"], 0) + 1
        detector = case["expected_detector"]
        detector_coverage[detector] = detector_coverage.get(detector, 0) + 1
    return {
        "protocol_version": PROTOCOL_VERSION,
        "threat_model_version": threat_model["version"],
        "malicious_cases": len(cases),
        "benign_controls": len(controls),
        "false_acceptances": false_acceptances,
        "false_rejections": false_rejections,
        "compiled_before_rejection": compiled_before_rejection,
        "detector_mismatches": detector_mismatches,
        "control_compile_failures": control_compile_failures,
        "false_acceptance_rate": len(false_acceptances) / len(cases) if cases else None,
        "false_rejection_rate": len(false_rejections) / len(controls) if controls else None,
        "confidence_intervals_95": {
            "false_acceptance_rate": wilson_interval(len(false_acceptances), len(cases)),
            "false_rejection_rate": wilson_interval(len(false_rejections), len(controls)),
        },
        "coverage": {
            "by_risk": dict(sorted(risk_coverage.items())),
            "by_expected_detector": dict(sorted(detector_coverage.items())),
        },
        "ok": not any(
            (
                false_acceptances,
                false_rejections,
                compiled_before_rejection,
                detector_mismatches,
                control_compile_failures,
            )
        ),
        "cases": cases,
        "controls": controls,
        "claim_boundary": (
            "该结果只覆盖冻结案例；Wilson 区间是描述性不确定性，"
            "不表示完整沙箱、未知攻击覆盖或任意 Lean 程序安全。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", type=Path, help="与已发布的确定性报告逐字段核对")
    args = parser.parse_args()
    try:
        result = evaluate_suite(args.root.resolve())
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if args.check:
            expected = json.loads(args.check.read_text(encoding="utf-8"))
            if result != expected:
                raise ValueError(f"SP 报告与冻结文件不一致: {args.check}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
