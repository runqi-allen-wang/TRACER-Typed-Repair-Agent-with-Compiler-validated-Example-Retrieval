"""合成定位预研究：生成等价的上下文/精简材料，真人计时，另存复核意见。"""
from __future__ import annotations

import argparse
import datetime
import json
import random
import re
import statistics
import time
import uuid
from pathlib import Path

from agent import ROOT, append_jsonl
from compiler import run_lean_file
from leancapsule.pack import pack_capsule
from leancapsule.replay import replay_capsule
from leancapsule.privacy import redact_value
from research import read_json, write_json

# 这是合成材料，不冒充真实用户缺陷；题解仅供准备与事后评审，不展示给参与者。
CASES = [
    ("(n : Nat) : n = n", "exact True.intro", "rfl", "所给证明属于 True，而目标是自然数相等"),
    ("(p q : Prop) (h : p ∧ q) : q ∧ p", "exact h", "exact ⟨h.2, h.1⟩", "合取的左右顺序与目标相反"),
    ("(p q : Prop) (h : p) : p ∧ q", "constructor\n  · exact h", "sorry", "只处理左支，缺少 q 的证明，现有假设不足"),
    ("(p : Prop) : p → p", "intro h", "intro h\n  exact h", "引入假设后仍有目标 p，未使用该假设完成证明"),
    ("(a b : Nat) (h : a = b) : b = a", "exact h.symmetry", "exact h.symm", "不存在 equality.symmetry 字段，应使用 Eq.symm 或 h.symm"),
    ("(xs : List Nat) : xs ++ [] = xs", "exact List.append_empty xs", "exact List.append_nil xs", "引用了不存在的 List.append_empty 常量"),
    ("(n : Nat) : n + 0 = n", "rw [Nat.add_comm]\n  rfl", "exact Nat.add_zero n", "交换后 0+n 与 n 不能对变量用 rfl 定义归约"),
    ("(p q : Prop) (h : p ∨ q) : q ∨ p", "cases h with\n  | inl hp => exact Or.inl hp\n  | inr hq => exact Or.inr hq", "cases h with\n  | inl hp => exact Or.inr hp\n  | inr hq => exact Or.inl hq", "析取分支注入方向写反，分支假设与所选目标不匹配"),
]


def valid_answer(answer):
    compact = re.sub(r"[\s；;，,:：。+＋]", "", answer).lower()
    return len(compact) >= 8 and compact not in {"错误位置原因", "位置原因", "passpass", "不知道不知道"}


def prepare(out):
    out.mkdir(parents=True, exist_ok=False)
    entries = []
    for index, (header, bad, good, rubric) in enumerate(CASES, 1):
        case_id = f"case{index:02d}"
        # 不使用已向参与者讲解过的两个旧 gallery 案例。
        prefix = "import Std\n\nnamespace Exercise\n\n"
        declarations = [f"theorem aux_{j:02d} (n : Nat) : n = n := by\n  rfl\n" for j in range(18)]
        position = 3 + index % 12
        target = f"theorem target {header} := by\n  {bad}\n"
        source = prefix + "\n".join(declarations[:position] + [target] + declarations[position:]) + "\nend Exercise\n"
        original = out / "original" / f"{case_id}.lean"
        original.parent.mkdir(exist_ok=True)
        original.write_text(source, encoding="utf-8")
        capsule = out / "capsules" / case_id
        manifest = pack_capsule(ROOT, original, capsule, theorem="Exercise.target", minimize=False,
                                source_kind="std", license_name="MIT", notes="TRACER 合成定位预研究，不是真实用户缺陷。")
        replay = replay_capsule(capsule, 60)
        short = (capsule / "Capsule.lean").read_text(encoding="utf-8")
        if manifest["expected"]["compile_ok"] or not replay["ok"] or manifest["extraction"]["mode"] != "standalone":
            raise ValueError("材料没有形成等价的可精简失败：" + case_id)
        if short == source or len(short.splitlines()) >= len(source.splitlines()):
            raise ValueError("原始/精简材料缺少真实差异：" + case_id)
        # 假设不足的案例不补充额外假设伪造修复；其余修正由独立编译确认。
        repaired_ok = None
        if good != "sorry":
            repaired = out / "reviewer" / f"{case_id}.lean"
            repaired.parent.mkdir(exist_ok=True)
            repaired.write_text(short.replace(bad, good), encoding="utf-8")
            repaired_ok = run_lean_file(repaired, 60).ok
            if not repaired_ok:
                raise ValueError("材料修正参考编译失败：" + case_id)
        entries.append({"case_id": case_id, "original_source": source, "capsule_source": short,
                        "expected": manifest["expected"], "rubric": rubric,
                        "original_lines": len(source.splitlines()), "capsule_lines": len(short.splitlines()),
                        "failure_reproduced": True, "reference_repair_compiles": repaired_ok})
    write_json(out / "materials.json", {"version": "human-synthetic-v1", "provenance": "合成控制案例",
               "scope": "源码精简的定位预研究；不能代表真实项目缺陷或 Capsule 全部价值", "cases": entries})
    return {"prepared": len(entries), "human_observations": 0, "verified_failure_pairs": len(entries)}


def assignment(materials, participant_number):
    if participant_number < 1:
        raise ValueError("参与者序号从 1 开始")
    rows = [{"case_id": case["case_id"], "representation": "original" if (index + participant_number) % 2 else "capsule"}
            for index, case in enumerate(materials["cases"])]
    # 相邻两位参与者看到同一组题的互补版本，单人不重复看到同一题。
    random.Random(20260828 + (participant_number - 1) // 2).shuffle(rows)
    return rows


def run_session(materials_path, out, participant_number, limit=600):
    materials = read_json(materials_path)
    if limit <= 0 or not materials.get("cases"):
        raise ValueError("材料或时间预算无效")
    participant = f"p{participant_number:02d}"
    out.mkdir(parents=True, exist_ok=True)
    directory = out / participant
    if directory.exists():
        raise ValueError("该参与者已有记录；请勿重复测试同一套题，保留中断记录联系研究负责人。")
    print("这是合成材料的定位预研究，不是考试。请勿提前阅读材料、调用 AI、编译器或搜索。")
    print("计时包含显示与阅读源码，不包含随后填写答案；同一人不能换编号重测。可随时 Ctrl+C 退出。")
    if input("确认自愿参与且未看过这套题，输入 YES：").strip() != "YES":
        return {"started": False}
    level = input("Lean 经验（none/basic/experienced）：").strip()
    if level not in {"none", "basic", "experienced"}:
        raise ValueError("经验选项无效")
    directory.mkdir(exist_ok=False)
    session = str(uuid.uuid4())
    tasks = assignment(materials, participant_number)
    write_json(directory / "session.json", {"session": session, "participant": participant,
        "experience": level, "consent": True, "materials_version": materials["version"],
        "tasks": tasks, "limit_seconds": limit, "timing": "显示源码到声明定位完成；不含答案录入",
        "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
    cases = {c["case_id"]: c for c in materials["cases"]}
    for number, task in enumerate(tasks, 1):
        print(f"\n任务 {number}/{len(tasks)}。请勿提前查看材料文件。")
        input("准备好后按 Enter；之后才会显示源码并开始计时：")
        source = cases[task["case_id"]][task["representation"] + "_source"]
        record_id = str(uuid.uuid4())
        append_jsonl(directory / "events.jsonl", {"record_id": record_id, **task, "event": "exposed",
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        started = time.perf_counter()
        print("\n".join(f"{i:3d} | {line}" for i, line in enumerate(source.splitlines(), 1)), flush=True)
        input(f"定位完成或决定放弃时按 Enter（预算 {limit:g} 秒，超时将标记）：")
        elapsed = time.perf_counter() - started
        gave_up = input("是否放弃/无法判断？输入 yes 或 no：").strip().lower()
        while gave_up not in {"yes", "no"}:
            gave_up = input("请输入 yes 或 no：").strip().lower()
        answer = "无法定位" if gave_up == "yes" else input("填写具体行号＋错误原因（不是复制提示文字）：").strip()
        while gave_up == "no" and not valid_answer(answer):
            answer = input("内容太短或是占位文字，请填写真实判断（不会重设计时）：").strip()
        append_jsonl(directory / "responses.jsonl", redact_value({"record_id": record_id, "session": session,
            "participant": participant, **task, "materials_version": materials["version"], "source_text": source,
            "elapsed_seconds": round(elapsed, 3), "limit_seconds": limit, "timed_out": elapsed > limit,
            "gave_up": gave_up == "yes", "answer": answer, "correctness": "pending", "actor": "human"}))
        print("已记录。此处不显示答案，避免影响后续任务。")
    return {"completed": len(tasks), "participant": participant, "correctness": "pending"}


def review_record(root, record_id, verdict, note, reviewer, reviewer_kind):
    responses = [json.loads(line) for file in root.glob("p*/responses.jsonl") for line in file.read_text(encoding="utf-8").splitlines()]
    if sum(row["record_id"] == record_id for row in responses) != 1:
        raise ValueError("复核对象不存在或重复")
    if not note.strip() or not reviewer.strip():
        raise ValueError("复核需填写评审者与依据，不能修改原始答案")
    path = root / "reviews.jsonl"
    old = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    if any(r["record_id"] == record_id for r in old):
        raise ValueError("已有复核，不静默覆盖")
    append_jsonl(path, {"record_id": record_id, "correct": verdict, "note": note,
                       "reviewer": reviewer, "reviewer_kind": reviewer_kind})
    return {"reviewed": True, "reviewer_kind": reviewer_kind}


def report(root, materials_path):
    materials = read_json(materials_path)
    cases = {c["case_id"]: c for c in materials["cases"]}
    reviews = [json.loads(s) for s in (root / "reviews.jsonl").read_text(encoding="utf-8").splitlines()] if (root / "reviews.jsonl").exists() else []
    review_map = {r["record_id"]: r for r in reviews}
    errors, observations, seen, participants = [], [], set(), []
    if len(review_map) != len(reviews) or any(r.get("correct") not in {"yes", "no"}
            or r.get("reviewer_kind") not in {"human", "ai_assisted"} or not r.get("note", "").strip() for r in reviews):
        errors.append("复核记录重复或缺少合法依据/身份")
    for path in root.glob("p*/session.json"):
        session = read_json(path)
        participants.append(session["participant"])
        expected_tasks = assignment(materials, int(session["participant"].removeprefix("p")))
        if session["tasks"] != expected_tasks or not session.get("consent") or session.get("materials_version") != materials["version"]:
            errors.append(session["participant"] + "：分组、同意或材料版本不符")
        response_file = path.parent / "responses.jsonl"
        rows = [json.loads(s) for s in response_file.read_text(encoding="utf-8").splitlines()] if response_file.exists() else []
        if [{k: r[k] for k in ("case_id", "representation")} for r in rows] != session["tasks"]:
            errors.append(session["participant"] + "：未完成全部已分配任务")
        for row in rows:
            key = (row["participant"], row["case_id"])
            if (key in seen or row["actor"] != "human" or row["session"] != session["session"]
                    or row["participant"] != session["participant"] or row.get("materials_version") != materials["version"]
                    or row["timed_out"] != (row["elapsed_seconds"] > row["limit_seconds"])
                    or row["source_text"] != cases[row["case_id"]][row["representation"] + "_source"]
                    or row["elapsed_seconds"] <= 0 or (not row["gave_up"] and not valid_answer(row["answer"]))):
                errors.append("重复、材料不符或无效答案")
            seen.add(key)
            observations.append(row)
    if len(participants) != len(set(participants)) or any(key not in {r["record_id"] for r in observations} for key in review_map):
        errors.append("参与者重复或复核记录没有对应答案")
    groups = {}
    for name in ("original", "capsule"):
        rows = [r for r in observations if r["representation"] == name]
        correct = [r for r in rows if review_map.get(r["record_id"], {}).get("correct") == "yes" and not r["gave_up"] and not r["timed_out"]]
        groups[name] = {"observations": len(rows), "reviewed_correct_within_budget": len(correct),
                       "timed_out": sum(r["timed_out"] for r in rows), "gave_up": sum(r["gave_up"] for r in rows),
                       "median_correct_seconds": statistics.median(r["elapsed_seconds"] for r in correct) if correct else None}
    human_reviewed = all(review_map.get(r["record_id"], {}).get("reviewer_kind") == "human" for r in observations)
    result = {"participants": len(participants), "observations": len(observations), "groups": groups,
        "errors": errors, "pending_reviews": sum(r["record_id"] not in review_map for r in observations),
        "human_review_complete": bool(observations) and human_reviewed and not errors,
        "status": "合成预研究；无真人记录" if not observations else "合成预研究；不作因果或真实项目外推结论",
        "note": "AI 辅助复核单独标记，不冒充真人复核。单人或未平衡样本不能证明定位收益。"}
    write_json(root / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--out", type=Path, default=ROOT / "results/human-materials-v1")
    run = sub.add_parser("run")
    run.add_argument("--materials", type=Path, default=ROOT / "results/human-materials-v1/materials.json")
    run.add_argument("--out", type=Path, default=ROOT / "results/human-study-v1")
    run.add_argument("--participant-number", type=int, required=True)
    run.add_argument("--limit", type=float, default=600)
    summary = sub.add_parser("report")
    summary.add_argument("--materials", type=Path, default=ROOT / "results/human-materials-v1/materials.json")
    summary.add_argument("--run", type=Path, default=ROOT / "results/human-study-v1")
    review = sub.add_parser("review")
    review.add_argument("--run", type=Path, default=ROOT / "results/human-study-v1")
    review.add_argument("--record-id", required=True)
    review.add_argument("--correct", choices=["yes", "no"], required=True)
    review.add_argument("--note", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--reviewer-kind", choices=["human", "ai_assisted"], required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args.out.resolve())
        elif args.command == "run":
            result = run_session(args.materials, args.out, args.participant_number, args.limit)
        elif args.command == "review":
            result = review_record(args.run, args.record_id, args.correct, args.note, args.reviewer, args.reviewer_kind)
        else:
            result = report(args.run, args.materials)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyboardInterrupt, EOFError) as exc:
        print(json.dumps({"ok": False, "error": str(exc) or "已中止；保留已经生成的记录，不补造计时"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
