"""离线计算 SP 安全回归的误放行、误拒绝与门禁位置。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compiler import candidate_safety_violation


PROTOCOL_VERSION = "tracer-sp-evaluation-v1"


def evaluate_suite(root: Path) -> dict:
    manifest = json.loads((root / "benchmarks/security/manifest.json").read_text(encoding="utf-8"))
    threat_model = json.loads((root / "benchmarks/security/threat_model.json").read_text(encoding="utf-8"))
    case_ids = [case["id"] for case in manifest]
    if case_ids != threat_model["cases"]:
        raise ValueError("威胁模型与 SP 清单不一致")

    cases = []
    for case in manifest:
        source = (root / case["file"]).read_text(encoding="utf-8")
        violation = candidate_safety_violation(source)
        cases.append({
            "id": case["id"],
            "risk": case["risk"],
            "expected_layer": case["expected_layer"],
            "rejected_before_compile": violation is not None,
            "observed_category": "unsafe_candidate" if violation else "allowed",
            "compile_invoked": False,
        })

    controls = []
    for control in threat_model["controls"]:
        source = (root / control["file"]).read_text(encoding="utf-8")
        violation = candidate_safety_violation(source)
        controls.append({
            "id": control["id"],
            "allowed": violation is None,
            "observed_category": "allowed" if violation is None else "unsafe_candidate",
        })

    false_acceptances = [item["id"] for item in cases if not item["rejected_before_compile"]]
    false_rejections = [item["id"] for item in controls if not item["allowed"]]
    compiled_before_rejection = [item["id"] for item in cases if item["compile_invoked"]]
    return {
        "protocol_version": PROTOCOL_VERSION,
        "threat_model_version": threat_model["version"],
        "malicious_cases": len(cases),
        "benign_controls": len(controls),
        "false_acceptances": false_acceptances,
        "false_rejections": false_rejections,
        "compiled_before_rejection": compiled_before_rejection,
        "false_acceptance_rate": len(false_acceptances) / len(cases) if cases else None,
        "false_rejection_rate": len(false_rejections) / len(controls) if controls else None,
        "ok": not false_acceptances and not false_rejections and not compiled_before_rejection,
        "cases": cases,
        "controls": controls,
        "claim_boundary": "该结果只覆盖冻结案例，不表示完整沙箱或任意 Lean 程序安全。",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        result = evaluate_suite(args.root.resolve())
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
