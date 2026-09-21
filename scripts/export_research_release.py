"""将通过门禁的 repair24 六臂批次导出为脱敏公开包。"""

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

from audit_research_release import FORMAT, SECRET_VALUE, audit_release  # noqa: E402
from leancapsule.privacy import redact_value  # noqa: E402
from research import ARMS, summarize, trial_path  # noqa: E402


REVIEW_FILE = "ai_assisted_review.csv"


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


def _strip_auth_fields(record: dict) -> dict:
    cleaned = json.loads(json.dumps(record, ensure_ascii=False))

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            value.pop("api_key_env", None)
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(cleaned)
    return cleaned


def _public_plan(plan: dict, source: Path) -> dict:
    cleaned = _strip_auth_fields(_public_value(plan, source))
    templates = cleaned.pop("prompt_templates", {})
    cleaned["prompt_template_files"] = sorted(f"protocol/{name}" for name in templates)
    cleaned["publication_note"] = "逐请求 prompt、供应商响应 ID、认证字段和归档失败原文未进入公开包。"
    return cleaned


def _copy_reviews(source_csv: Path, destination: Path, source: Path) -> int:
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or "review_mode" not in fields:
        raise ValueError("六臂复核表缺少表头或 review_mode")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _public_value(value, source) for key, value in row.items()})
    return len(rows)


def _retry_inventory(source: Path) -> dict:
    retry = source / "retry_history"
    attempts = sorted(path for path in retry.rglob("attempt-*") if path.is_dir()) if retry.exists() else []
    round_records = 0
    for path in attempts:
        for runs in path.rglob("runs.jsonl"):
            round_records += sum(bool(line.strip()) for line in runs.read_text(encoding="utf-8").splitlines())
    return {"attempt_directories": len(attempts), "round_records": round_records}


def _readable_files(proofs: list[Path], staging: Path, counts: dict) -> str:
    lines = [
        "# repair24 六臂实验文件说明", "",
        f"本发布包包含 {counts['tasks']} 个任务、{counts['attempts']} 条有效逐轮记录、",
        f"{counts['successes']} 个成功任务及 {counts['proof_files']} 个对应 Lean 证明。", "",
        "## 核心文件", "",
        "- `README.md`：结果、解释边界与隐私处理。",
        "- `plan.sanitized.json`：冻结任务顺序与非敏感模型配置。",
        "- `preregistration.json`：正式六臂预注册。",
        "- `trials.jsonl`：864 条任务级结果。",
        "- `attempts.sanitized.jsonl`：逐轮候选、反馈、usage 与编译诊断，不含完整请求 prompt。",
        "- `ai_assisted_review.csv`：864 条显式标注模式的复核记录。",
        "- `ai_review_report.json`：AI 辅助复核方法、覆盖数、警告数与错误清单。",
        "- `summary.json`：描述性汇总与配对差异。",
        "- `MANIFEST.json`：除自身外全部文件的相对路径与字节数。",
        "- `protocol/`：本批次实际冻结的静态提示模板。",
        "- `solutions/`：每个成功任务对应的独立 Lean 文件。", "",
        "## 成功证明", "",
    ]
    lines.extend(f"- `{path.relative_to(staging).as_posix()}`" for path in sorted(proofs))
    return "\n".join(lines) + "\n"


def _readme(summary: dict, counts: dict, plan: dict) -> str:
    rows = [
        "| 模型 | 研究臂 | 任务 | pass@1 | 三轮内通过 | 平均轮数 | tokens |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["summary"]:
        rows.append(
            f"| {row['model']} | {row['arm']} | {row['tasks']} | "
            f"{row['first']} | {row['success']} | {row['avg_rounds']:.3f} | {row['total_tokens']} |"
        )
    retry_note = ""
    if counts["reported_retry_attempts"] != counts["archived_retry_attempts"]:
        retry_note = (
            f" 运行期 completion 字段报告 {counts['reported_retry_attempts']} 次，"
            f"发布时从归档目录实测为 {counts['archived_retry_attempts']} 次；"
            "两者均保留，不静默改写原记录。"
        )
    return "\n".join([
        "# TRACER repair24 正式六臂实验公开包", "",
        f"实验编号：`{summary['experiment_id']}`。本包公开 {counts['tasks']} 个任务、",
        f"{counts['attempts']} 条有效逐轮记录、{counts['proof_files']} 个成功证明和 AI 辅助复核表。", "",
        *rows, "",
        "六臂在同模型、同题、同重复和同轮数预算下比较。重复不是新数学题；"
        "表格是描述性结果，不自动声称统计显著、因果增益、跨供应商泛化或 SOTA。", "",
        "## 发布处理", "",
        "公开逐轮记录保留候选、反馈载荷、编译诊断、usage、结束原因和非敏感配置。"
        "逐请求完整 prompt、供应商响应 ID、认证字段、本机绝对路径和 `retry_history` 原文不进入本包。",
        f"本批次实测 {counts['archived_retry_attempts']} 个归档尝试目录，含 "
        f"{counts['archived_retry_round_records']} 条失败轮次；预算账本另有 "
        f"{counts['unmatched_call_reservations']} 次没有对应轮次的调用预留。{retry_note}", "",
        "## 复核口径", "",
        f"{counts['proof_files']} 个成功证明需通过独立 Lean 复编译和 AI 辅助检查。"
        "复核表显式记录 `review_mode=ai_assisted`；这不是纯人工复核。", "",
        "完整文件索引见 `FILES.md`，机器可读清单见 `MANIFEST.json`。", "",
    ])


def export_release(source: Path, out: Path) -> dict:
    source = source.resolve()
    out = out.resolve()
    if out.exists():
        raise ValueError(f"输出目录已存在: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = summarize(source)
    review_modes = summary.get("review_mode_counts", {})
    if not (
        summary.get("release_ready") is True
        and summary.get("manual_review_complete") is True
        and review_modes
        and set(review_modes) == {"ai_assisted"}
    ):
        raise ValueError("本地批次未通过完整轨迹、证明和 AI 辅助复核门禁")
    plan = json.loads((source / "plan.json").read_text(encoding="utf-8"))
    benchmark = json.loads((source / "benchmark.json").read_text(encoding="utf-8"))
    completion = json.loads((source / "completion.json").read_text(encoding="utf-8"))
    initial = json.loads((source / "initial_compilation.json").read_text(encoding="utf-8"))
    examples = json.loads((source / "examples.json").read_text(encoding="utf-8"))
    failure_notes = json.loads((source / "failure_notes.json").read_text(encoding="utf-8"))
    ai_review = json.loads((source / "ai_review_report.json").read_text(encoding="utf-8"))
    preregistration = plan.get("preregistration")
    if not isinstance(preregistration, dict):
        raise ValueError("本地批次缺少机器可读预注册")
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    proofs: list[Path] = []
    attempts_count = 0
    trial_rows: list[dict] = []
    try:
        _write_json(staging / "plan.sanitized.json", _public_plan(plan, source))
        _write_json(staging / "preregistration.json", _strip_auth_fields(_public_value(preregistration, source)))
        _write_json(staging / "benchmark.json", _public_value(benchmark, source))
        _write_json(staging / "examples.sanitized.json", _public_value(examples, source))
        _write_json(staging / "failure_notes.sanitized.json", _public_value(failure_notes, source))
        _write_json(staging / "initial_compilation.sanitized.json", _public_value(initial, source))
        _write_json(staging / "ai_review_report.json", _public_value(ai_review, source))

        (staging / "protocol").mkdir(parents=True, exist_ok=True)
        for name, text in plan.get("prompt_templates", {}).items():
            (staging / "protocol" / name).write_text(text, encoding="utf-8", newline="\n")

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
                        "arm": task["arm"],
                    })
                    text = json.dumps(public, ensure_ascii=False, sort_keys=True)
                    _reject_secret_text(text, "attempts.sanitized.jsonl")
                    attempts_handle.write(text + "\n")
                    attempts_count += 1
                public_trial = _public_value(trial, source)
                public_trial["attempt_count"] = len(rows)
                public_trial["solution"] = None
                if trial.get("compile_ok") is True:
                    condition = ARMS[task["arm"]][0]
                    candidates = list((local / "solutions" / condition).glob("*.lean"))
                    if len(candidates) != 1:
                        raise ValueError(f"成功任务缺少唯一证明: {task}")
                    relative = Path("solutions") / task["model_id"] / str(task["repeat"]) / task["arm"] / f"{task['problem_id']}.lean"
                    destination = staging / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(candidates[0], destination)
                    public_trial["solution"] = relative.as_posix()
                    proofs.append(destination)
                trial_rows.append(public_trial)

        with (staging / "trials.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for row in trial_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        reviews = _copy_reviews(source / "manual_review.csv", staging / REVIEW_FILE, source)

        retry = _retry_inventory(source)
        attempted_calls = completion.get("budget", {}).get("attempted_calls")
        if not isinstance(attempted_calls, int):
            raise ValueError("completion.json 缺少预算账本调用预留数")
        unmatched = attempted_calls - attempts_count - retry["round_records"]
        if unmatched < 0:
            raise ValueError("预算账本调用预留数小于当前与归档轮次记录总数")
        counts = {
            "tasks": len(trial_rows),
            "attempts": attempts_count,
            "successes": len(proofs),
            "failed_tasks": len(trial_rows) - len(proofs),
            "proof_files": len(proofs),
            "review_rows": reviews,
            "reported_retry_attempts": completion.get("archived_retry_attempts", 0),
            "archived_retry_attempts": retry["attempt_directories"],
            "archived_retry_round_records": retry["round_records"],
            "attempted_call_reservations": attempted_calls,
            "unmatched_call_reservations": unmatched,
        }
        public_completion = _public_value(completion, source)
        public_completion["publication_retry_inventory"] = {
            "reported_attempts": counts["reported_retry_attempts"],
            "observed_attempt_directories": counts["archived_retry_attempts"],
            "observed_round_records": counts["archived_retry_round_records"],
        }
        public_summary = _public_value(summary, source)
        public_summary["publication_retry_inventory"] = public_completion["publication_retry_inventory"]
        _write_json(staging / "completion.sanitized.json", public_completion)
        _write_json(staging / "summary.json", public_summary)
        (staging / "README.md").write_text(_readme(public_summary, counts, plan), encoding="utf-8", newline="\n")
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
                "included": ["task summaries", "sanitized attempts", "successful proofs", "AI-assisted review", "frozen prompt templates"],
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
