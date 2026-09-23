"""从公开脱敏发布包构建静态 Demo 数据。

该脚本不调用模型、不访问网络，也不读取未发布实验目录。生成结果只包含
repair24 冻结题面、公开诊断和已经独立复编译通过的证明。
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "published" / "research-six-arm-313f437f"
OUTPUT = ROOT / "demo" / "demo-data.js"


def proof_region(source: str) -> str:
    start_marker = "-- PROOF_START"
    end_marker = "-- PROOF_END"
    start = source.index(start_marker) + len(start_marker)
    end = source.index(end_marker, start)
    return source[start:end].strip()


def verified_solution_paths() -> set[Path]:
    rows = [
        json.loads(line)
        for line in (RELEASE / "trials.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {
        RELEASE / row["solution"]
        for row in rows
        if row.get("compile_ok") and row.get("independent_compile_ok") and row.get("solution")
    }


def selected_solution(problem_id: str, verified: set[Path]) -> Path:
    candidates = sorted(
        path for path in (RELEASE / "solutions").glob(f"**/{problem_id}.lean") if path in verified
    )
    if not candidates:
        raise ValueError(f"找不到公开成功证明：{problem_id}")

    # 优先使用 Flash、第一次重复、最基础实验臂；缺失时退回排序后的首个公开解。
    preferred = [
        path
        for path in candidates
        if "deepseek_flash_v41" in path.parts and "1" in path.parts and "A" in path.parts
    ]
    return preferred[0] if preferred else candidates[0]


def arm_from_solution(path: Path) -> str:
    relative = path.relative_to(RELEASE / "solutions")
    return relative.parts[2]


def build() -> dict:
    benchmark = json.loads((RELEASE / "benchmark.json").read_text(encoding="utf-8"))
    initial = json.loads(
        (RELEASE / "initial_compilation.sanitized.json").read_text(encoding="utf-8")
    )

    verified = verified_solution_paths()
    cases = []
    for problem in benchmark["problems"]:
        problem_id = problem["id"]
        diagnostic = initial[problem_id]
        solution_path = selected_solution(problem_id, verified)
        solution_text = solution_path.read_text(encoding="utf-8")
        category = diagnostic["diagnostic"]["category"]

        cases.append(
            {
                "id": problem_id,
                "theorem": problem["theorem"],
                "topic": problem["tags"][0],
                "difficulty": problem["difficulty"],
                "category": category,
                "initialProof": proof_region(problem["source_text"]),
                "initialDiagnostic": diagnostic["raw_diagnostics"],
                "structuredFeedback": diagnostic["diagnostic"]["feedback"],
                "repairedProof": proof_region(solution_text),
                "solutionPath": solution_path.relative_to(ROOT).as_posix(),
                "solutionArm": arm_from_solution(solution_path),
                "compileMs": diagnostic["compile_elapsed_ms"],
            }
        )

    return {
        "evidence": {
            "release": "research-six-arm-313f437f",
            "tasks": 864,
            "firstPass": 735,
            "withinThree": 811,
            "recovered": 76,
            "firstRate": 85.1,
            "withinThreeRate": 93.9,
            "deltaPoints": 8.8,
            "caseCount": len(cases),
            "topicCount": len({case["topic"] for case in cases}),
            "categoryCount": len({case["category"] for case in cases}),
        },
        "cases": cases,
    }


def main() -> int:
    payload = json.dumps(build(), ensure_ascii=False, indent=2)
    OUTPUT.write_text(f"window.TRACER_DEMO = {payload};\n", encoding="utf-8")
    print(f"已生成 {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
