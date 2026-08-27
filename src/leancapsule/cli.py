"""LeanCapsule 命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .issue import render_issue
from .gallery import build_gallery_index, write_gallery_reports
from .audit import audit_directory
from .feedback import CapsuleFeedback
from .pack import pack_capsule
from .replay import replay_capsule
from .verify import verify_directory


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LeanCapsule：打包、回放和验证 Lean 失败工件")
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack", help="生成 capsule")
    pack.add_argument("--project", type=Path, default=Path("."))
    pack.add_argument("--file", type=Path, required=True)
    select = pack.add_mutually_exclusive_group(required=True)
    select.add_argument("--theorem")
    select.add_argument("--lines")
    pack.add_argument("--out", type=Path, required=True)
    pack.add_argument("--timeout", type=float, default=60.0)
    pack.add_argument("--no-minimize-imports", action="store_true", help="不尝试删除 imports")
    pack.add_argument("--taxonomy", help="错误家族标签")
    pack.add_argument("--source-kind", help="案例来源类型，例如 std、mathlib、project_local")
    pack.add_argument("--license", dest="license_name", default="未声明")
    pack.add_argument("--source-url")
    pack.add_argument("--notes", default="由 pack 命令生成，请人工补充来源。")
    replay = sub.add_parser("replay", help="回放单个 capsule")
    replay.add_argument("capsule", type=Path)
    replay.add_argument("--timeout", type=float, default=180.0)
    verify = sub.add_parser("verify", help="批量验证 capsule")
    verify.add_argument("directory", type=Path)
    verify.add_argument("--timeout", type=float, default=180.0)
    issue = sub.add_parser("issue", help="生成 issue Markdown")
    issue.add_argument("capsule", type=Path)
    issue.add_argument("--out", type=Path, required=True)
    gallery = sub.add_parser("gallery", help="生成 gallery 索引并检查覆盖")
    gallery.add_argument("directory", type=Path)
    gallery.add_argument("--out", type=Path, required=True)
    gallery.add_argument("--csv", dest="csv_out", type=Path)
    gallery.add_argument("--markdown", dest="markdown_out", type=Path)
    audit = sub.add_parser("audit", help="执行公开 capsule 的发布前静态审计")
    audit.add_argument("directory", type=Path)
    feedback = sub.add_parser("feedback", help="从已有的 Ax/Lean 编译结果生成紧凑反馈，不重新编译")
    feedback.add_argument("--input", default="-", help="编译结果 JSON；默认从标准输入读取")
    feedback.add_argument("--state", type=Path, help="可选的逐题状态文件；读取后原子更新")
    feedback.add_argument("--history-limit", type=int, default=4)
    feedback.add_argument("--max-feedback-chars", type=int, default=1600)
    feedback.add_argument("--fingerprint-limit", type=int, default=64)
    return parser


def _read_feedback_input(value: str) -> dict:
    text = sys.stdin.read() if value == "-" else Path(value).read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("feedback 输入必须是 JSON object")
    return payload


def _write_feedback_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "pack":
            result = pack_capsule(args.project, args.file, args.out, theorem=args.theorem, lines=args.lines, timeout=args.timeout, minimize=not args.no_minimize_imports, taxonomy=args.taxonomy, source_kind=args.source_kind, license_name=args.license_name, source_url=args.source_url, notes=args.notes)
            print(json.dumps({"ok": True, "capsule": str(args.out), "diagnostic_key": result["expected"]["diagnostic_key"]}, ensure_ascii=False))
            return 0
        if args.command == "replay":
            result = replay_capsule(args.capsule, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 1
        if args.command == "verify":
            result = verify_directory(args.directory, timeout=args.timeout)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 1
        if args.command == "issue":
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(render_issue(args.capsule), encoding="utf-8")
            print(json.dumps({"ok": True, "out": str(args.out)}, ensure_ascii=False))
            return 0
        if args.command == "gallery":
            result = build_gallery_index(args.directory)
            write_gallery_reports(result, args.out, args.csv_out, args.markdown_out)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 1
        if args.command == "audit":
            result = audit_directory(args.directory)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result.get("ok") else 1
        if args.command == "feedback":
            payload = _read_feedback_input(args.input)
            state = {}
            if args.state and args.state.exists():
                loaded = json.loads(args.state.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("feedback state 必须是 JSON object")
                state = loaded
            formatter = CapsuleFeedback(
                history_limit=args.history_limit,
                max_feedback_chars=args.max_feedback_chars,
                fingerprint_limit=args.fingerprint_limit,
                state=state,
            )
            result = formatter.observe_ax(payload, round_no=payload.get("round"))
            if args.state:
                _write_feedback_state(args.state, formatter.export_state())
            print(json.dumps(result, ensure_ascii=False))
            return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 2
