"""将通过门禁的 Feedback Study v1 本地批次导出为脱敏公开包。"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_feedback_study import FORMAT, SECRET_VALUE, audit_release  # noqa: E402
from feedback_study import AI_ASSISTED_REVIEW_FILE, review_path, summarize, trial_path  # noqa: E402
from leancapsule.privacy import redact_value  # noqa: E402


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _public_value(value: Any, source: Path) -> Any:
    return redact_value(value, (ROOT, source, Path.home(), Path(tempfile.gettempdir())))


def _reject_secret_text(text: str, location: str) -> None:
    if SECRET_VALUE.search(text):
        raise ValueError(f"导出内容疑似包含认证值: {location}")


def _public_attempt(row: dict, source: Path) -> dict:
    cleaned = _public_value(row, source)
    cleaned.pop("prompt", None)
    response = cleaned.get("provider_response")
    if isinstance(response, dict):
        response.pop("id", None)
    return cleaned


def _public_plan(plan: dict, source: Path) -> dict:
    cleaned = _public_value(plan, source)
    cleaned.pop("prompt_templates", None)
    for model in cleaned.get("config", {}).get("models", []):
        if isinstance(model, dict):
            model.pop("api_key_env", None)
    cleaned["prompt_template_files"] = ["protocol/feedback.txt", "protocol/proof_contract.txt"]
    cleaned["publication_note"] = "逐请求 prompt、供应商响应 ID、认证字段和传输失败原文未进入公开包。"
    return cleaned


def _copy_reviews(source_csv: Path, destination: Path, source: Path) -> int:
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields:
        raise ValueError("AI 辅助复核表缺少表头")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _public_value(value, source) for key, value in row.items()})
    return len(rows)


def _readable_files(proofs: list[Path], staging: Path, counts: dict) -> str:
    lines = [
        "# Feedback Study v1 文件说明",
        "",
        f"本发布包包含 {counts['tasks']} 个任务、{counts['attempts']} 条逐轮记录、"
        f"{counts['successes']} 个成功任务及 {counts['proof_files']} 个对应 Lean 证明。",
        "",
        "## 核心文件",
        "",
        "- `README.md`：结果、解释边界与隐私处理。",
        "- `plan.sanitized.json`：冻结任务顺序与非敏感模型配置。",
        "- `benchmark.json`：冻结 repair24 题目。",
        "- `trials.jsonl`：216 条任务级结果。",
        "- `attempts.sanitized.jsonl`：逐轮候选、反馈、usage 与编译诊断，不含完整请求 prompt。",
        "- `ai_assisted_review.csv`：216 条显式标注模式的复核记录。",
        "- `summary.json`：描述性汇总与逐题配对差值。",
        "- `MANIFEST.json`：除自身外全部文件的相对路径与字节数。",
        "- `protocol/`：公开的冻结协议与静态提示模板。",
        "- `solutions/`：每个成功任务对应的独立 Lean 文件。",
        "",
        "## 成功证明",
        "",
    ]
    lines.extend(f"- `{path.relative_to(staging).as_posix()}`" for path in sorted(proofs))
    return "\n".join(lines) + "\n"


def _readme(summary: dict, counts: dict) -> str:
    by_rep = {row["representation"]: row for row in summary["summary"]}
    table = [
        "| 表示 | 任务 | pass@1 | 三轮内通过 | 平均轮数 | tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("raw", "normalized", "structured"):
        row = by_rep[name]
        table.append(
            f"| {name} | {row['tasks']} | {row['pass_at_1']} | {row['pass_within_budget']} | "
            f"{row['avg_rounds']:.3f} | {row['total_tokens']} |"
        )
    return "\n".join([
        "# TRACER Feedback Study v1：DeepSeek 本地批次公开包",
        "",
        f"实验编号：`{summary['experiment_id']}`。本包公开 {counts['tasks']} 个 repair24 任务的任务级结果、"
        f"{counts['attempts']} 条逐轮记录、{counts['proof_files']} 个成功证明和 AI 辅助复核表。",
        "",
        *table,
        "",
        "三种表示在同模型、同题目、同重复和同轮数预算下比较。结果仅作单模型、24 题、三重复的描述性证据；"
        "不得把 216 个任务当成 216 道独立题，也不声称统计显著、因果增益或跨模型泛化。",
        "",
        "## 发布处理",
        "",
        "公开逐轮记录保留候选、反馈载荷、编译诊断、usage、结束原因和非敏感模型配置。"
        "逐请求完整 prompt、供应商响应 ID、认证字段、本机绝对路径和 `retry_history` 原文不进入本包。"
        f"{counts['archived_retry_attempts']} 次传输失败以计数形式披露；其归档中共有 "
        f"{counts['archived_retry_round_records']} 条失败轮次记录。预算账本另有 "
        f"{counts['unmatched_call_reservations']} 次没有对应轮次记录的调用预留，不能据此断言供应商完成了请求。",
        "",
        "静态提示模板单独保存在 `protocol/`，冻结题目保存在 `benchmark.json`；因此可以核对实验契约，"
        "但不能从公开包还原供应商内部请求标识或失败连接的服务端原文。费用参数未冻结，美元成本保持未知，不能解释为零。",
        "",
        "## 复核口径",
        "",
        "199 个成功证明均经过独立 Lean 复编译和 AI 辅助检查。复核表明确记录 `review_mode=ai_assisted`；"
        "它不是纯人工复核，也不替代对更广题库、其他模型或未知安全攻击的验证。",
        "",
        "完整文件索引见 `FILES.md`，机器可读清单见 `MANIFEST.json`。",
        "",
    ])


def export_release(source: Path, out: Path) -> dict:
    source = source.resolve()
    out = out.resolve()
    if out.exists():
        raise ValueError(f"输出目录已存在: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(source)
    if not (
        summary.get("release_ready") is True
        and summary.get("review_mode") == "ai_assisted"
        and summary.get("ai_assisted_review_complete") is True
    ):
        raise ValueError("本地批次未通过完整轨迹、证明和 AI 辅助复核门禁")
    plan = json.loads((source / "plan.json").read_text(encoding="utf-8"))
    benchmark = json.loads((source / "benchmark.json").read_text(encoding="utf-8"))
    completion = json.loads((source / "completion.json").read_text(encoding="utf-8"))
    initial = json.loads((source / "initial_compilation.json").read_text(encoding="utf-8"))
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    proofs: list[Path] = []
    attempts_count = 0
    trial_rows: list[dict] = []
    try:
        _write_json(staging / "plan.sanitized.json", _public_plan(plan, source))
        _write_json(staging / "benchmark.json", _public_value(benchmark, source))
        _write_json(staging / "completion.sanitized.json", _public_value(completion, source))
        _write_json(staging / "initial_compilation.sanitized.json", _public_value(initial, source))
        _write_json(staging / "summary.json", _public_value(summary, source))
        protocol = ROOT / "experiments" / "feedback_study.protocol.json"
        (staging / "protocol").mkdir(parents=True, exist_ok=True)
        shutil.copy2(protocol, staging / "protocol" / protocol.name)
        for name in ("feedback.txt", "proof_contract.txt"):
            target = staging / "protocol" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "prompts" / name, target)

        attempts_path = staging / "attempts.sanitized.jsonl"
        with attempts_path.open("w", encoding="utf-8", newline="\n") as attempts_handle:
            for task in plan["tasks"]:
                local = trial_path(source, task)
                trial = json.loads((local / "trial.json").read_text(encoding="utf-8"))
                rows = [json.loads(line) for line in (local / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
                for row in rows:
                    public = _public_attempt(row, source)
                    public.update({
                        "model_id": task["model_id"],
                        "repeat": task["repeat"],
                        "representation": task["representation"],
                    })
                    text = json.dumps(public, ensure_ascii=False, sort_keys=True)
                    _reject_secret_text(text, "attempts.sanitized.jsonl")
                    attempts_handle.write(text + "\n")
                    attempts_count += 1
                public_trial = _public_value(trial, source)
                public_trial["attempt_count"] = len(rows)
                public_trial["solution"] = None
                if trial.get("compile_ok") is True:
                    candidates = list((local / "solutions" / "B").glob("*.lean"))
                    if len(candidates) != 1:
                        raise ValueError(f"成功任务缺少唯一证明: {task}")
                    relative = Path("solutions") / task["model_id"] / str(task["repeat"]) / task["representation"] / f"{task['problem_id']}.lean"
                    destination = staging / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidates[0], destination)
                    public_trial["solution"] = relative.as_posix()
                    proofs.append(destination)
                trial_rows.append(public_trial)

        with (staging / "trials.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for row in trial_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        reviews = _copy_reviews(review_path(source), staging / AI_ASSISTED_REVIEW_FILE, source)
        archived_round_records = sum(
            len([line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()])
            for path in (source / "retry_history").rglob("runs.jsonl")
        ) if (source / "retry_history").exists() else 0
        attempted_calls = completion.get("budget", {}).get("attempted_calls")
        if not isinstance(attempted_calls, int):
            raise ValueError("completion.json 缺少预算账本调用预留数")
        unmatched_reservations = attempted_calls - attempts_count - archived_round_records
        if unmatched_reservations < 0:
            raise ValueError("预算账本调用预留数小于当前与归档逐轮记录总数")
        counts = {
            "tasks": len(trial_rows),
            "attempts": attempts_count,
            "successes": len(proofs),
            "failed_tasks": len(trial_rows) - len(proofs),
            "proof_files": len(proofs),
            "review_rows": reviews,
            "archived_retry_attempts": summary.get("archived_transport_retry_attempts", 0),
            "archived_retry_round_records": archived_round_records,
            "attempted_call_reservations": attempted_calls,
            "unmatched_call_reservations": unmatched_reservations,
        }
        (staging / "README.md").write_text(_readme(summary, counts), encoding="utf-8", newline="\n")
        (staging / "FILES.md").write_text(_readable_files(proofs, staging, counts), encoding="utf-8", newline="\n")

        for path in staging.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".json", ".jsonl", ".csv", ".md", ".txt", ".lean"}:
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                _reject_secret_text(text, path.relative_to(staging).as_posix())
                path.write_text(text, encoding="utf-8", newline="\n")
        files = sorted(path for path in staging.rglob("*") if path.is_file())
        manifest = {
            "format": FORMAT,
            "experiment_id": summary["experiment_id"],
            "counts": counts,
            "privacy": {
                "included": ["task summaries", "sanitized attempts", "successful proofs", "AI-assisted review", "static prompt templates"],
                "excluded": ["per-request prompt", "provider response ID", "authentication fields", "local absolute paths", "retry_history contents"],
                "inventory_method": "relative path and byte size",
            },
            "files": [
                {"path": path.relative_to(staging).as_posix(), "size_bytes": path.stat().st_size}
                for path in files
            ],
        }
        _write_json(staging / "MANIFEST.json", manifest)
        audit = audit_release(staging)
        if not audit["ok"]:
            raise ValueError("导出后的发布审计失败: " + "; ".join(audit["errors"][:5]))
        staging.replace(out)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {"ok": True, "out": str(out), **counts}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = export_release(args.run, args.out)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
