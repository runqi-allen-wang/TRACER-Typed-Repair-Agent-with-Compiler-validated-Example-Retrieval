"""确定性发现并筛查公开 Git 历史中的 Lean 证明修复候选。"""

from __future__ import annotations

import argparse
import bisect
import json
import re
import sys
from pathlib import Path
from typing import Any

from compiler import DECLARATION_RE, _COMMAND_START
from real_repairs import (
    PROTOCOL_VERSION,
    _git,
    _git_file,
    _normalized_header,
    _proof_delimiter,
    _resolve_revision,
    build_case,
)
from research import write_json


INVENTORY_VERSION = "tracer-real-candidate-inventory-v1"
SCREEN_VERSION = "tracer-real-candidate-screen-v1"


def declaration_names(source: str) -> list[str]:
    """列出当前声明定位器能够无歧义处理的 theorem/lemma 完全限定名。"""

    return list(_parts_by_name(source))


def _changed_lean_files(repo: Path, before: str, after: str) -> list[str]:
    output = _git(repo, "diff", "--name-only", "--diff-filter=M", before, after, "--", "*.lean")
    return sorted(line.strip() for line in output.splitlines() if line.strip())


def _first_parent_pairs(repo: Path, endpoint: str, max_commits: int) -> list[tuple[str, str]]:
    if max_commits <= 0:
        raise ValueError("max_commits 必须为正整数")
    revisions = [
        line.strip()
        for line in _git(repo, "rev-list", "--first-parent", f"--max-count={max_commits + 1}", endpoint).splitlines()
        if line.strip()
    ]
    return list(zip(revisions[:-1], revisions[1:]))


def _parts_by_name(source: str) -> dict[str, dict[str, Any]]:
    """单次线性扫描提取声明，避免对大型形式化文件反复扫描前缀。"""

    declarations = {match.start(): match for match in DECLARATION_RE.finditer(source)}
    qualified: list[tuple[str, int]] = []
    blocks: list[tuple[str, str | None]] = []
    offset = 0
    for line in source.splitlines(keepends=True):
        declaration = declarations.get(offset)
        if declaration is not None:
            namespace_parts: list[str] = []
            for kind, name in blocks:
                if kind != "namespace" or not name:
                    continue
                if name.startswith("_root_."):
                    namespace_parts = name.removeprefix("_root_").lstrip(".").split(".")
                else:
                    namespace_parts.extend(name.split("."))
            short_name = declaration.group("name")
            name = ".".join((*namespace_parts, short_name)) if namespace_parts else short_name
            qualified.append((name, declaration.start()))

        namespace = re.match(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.']*)\s*$", line)
        section = re.match(r"^\s*section(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$", line)
        closing = re.match(r"^\s*end(?:\s+([A-Za-z_][A-Za-z0-9_.']*))?\s*$", line)
        if namespace:
            blocks.append(("namespace", namespace.group(1)))
        elif section:
            blocks.append(("section", section.group(1)))
        elif closing and blocks:
            closing_name = closing.group(1)
            if closing_name:
                for index in range(len(blocks) - 1, -1, -1):
                    block_name = blocks[index][1]
                    if block_name and block_name.split(".")[-1] == closing_name.split(".")[-1]:
                        del blocks[index:]
                        break
            else:
                blocks.pop()
        offset += len(line)

    command_starts = [match.start() for match in _COMMAND_START.finditer(source)]
    result: dict[str, dict[str, Any]] = {}
    for name, start in qualified:
        if name in result:
            continue
        try:
            next_index = bisect.bisect_right(command_starts, start)
            end = command_starts[next_index] if next_index < len(command_starts) else len(source)
            scope = source[start:end]
            delimiter = _proof_delimiter(scope)
            result[name] = {
                "scope_start": start,
                "scope_end": end,
                "header": scope[:delimiter].strip(),
                "proof": scope[delimiter + 2:].strip(),
                "delimiter": start + delimiter,
            }
        except ValueError:
            continue
    return result


def _cached_git_file(
    repo: Path, cache: dict[tuple[str, str], str], revision: str, relative: str,
) -> str:
    key = (revision, relative)
    if key not in cache:
        cache[key] = _git_file(repo, revision, relative)
    return cache[key]


def _slug(project_id: str, theorem: str, used: set[str]) -> str:
    stem = re.sub(r"[^a-z0-9]+", "_", theorem.lower()).strip("_") or "theorem"
    base = f"{project_id}_{stem}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def scan_history(
    repo: Path,
    *,
    project_id: str,
    source_repository: str,
    source_license: str,
    endpoint: str = "HEAD",
    max_commits: int = 120,
) -> dict[str, Any]:
    """枚举固定端点之前窗口内的全部可解析纯证明变化，不运行 Lean。"""

    repo = repo.resolve()
    fixed_revision = _resolve_revision(repo, endpoint)
    if _resolve_revision(repo, "HEAD") != fixed_revision:
        raise ValueError("扫描端点必须等于当前检出的 HEAD")
    pairs = _first_parent_pairs(repo, fixed_revision, max_commits)
    endpoint_cache: dict[str, dict[str, dict[str, Any]]] = {}
    source_cache: dict[tuple[str, str], str] = {}
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    used_ids: set[str] = set()
    files_considered = 0

    for after, before in pairs:
        for relative in _changed_lean_files(repo, before, after):
            files_considered += 1
            try:
                before_source = _cached_git_file(repo, source_cache, before, relative)
                after_source = _cached_git_file(repo, source_cache, after, relative)
            except ValueError:
                continue
            before_parts = _parts_by_name(before_source)
            after_parts = _parts_by_name(after_source)
            if relative not in endpoint_cache:
                try:
                    endpoint_source = _cached_git_file(repo, source_cache, fixed_revision, relative)
                except ValueError:
                    continue
                endpoint_cache[relative] = _parts_by_name(endpoint_source)
            endpoint_parts = endpoint_cache[relative]
            for theorem in sorted(set(before_parts) & set(after_parts) & set(endpoint_parts)):
                key = (relative, theorem)
                if key in selected:
                    continue
                old, changed, final = before_parts[theorem], after_parts[theorem], endpoint_parts[theorem]
                headers = {
                    _normalized_header(old["header"]),
                    _normalized_header(changed["header"]),
                    _normalized_header(final["header"]),
                }
                if len(headers) != 1 or old["proof"] == changed["proof"] or old["proof"] == final["proof"]:
                    continue
                selected[key] = {
                    "id": _slug(project_id, theorem, used_ids),
                    "before_revision": before,
                    "fixed_revision": fixed_revision,
                    "file": relative,
                    "theorem": theorem,
                    "change_revision": after,
                }

    candidates = sorted(selected.values(), key=lambda row: (row["file"], row["theorem"]))
    return {
        "version": INVENTORY_VERSION,
        "status": "deterministic-history-scan",
        "project_id": project_id,
        "source_repository": source_repository,
        "source_license": source_license,
        "endpoint_revision": fixed_revision,
        "history_policy": {
            "traversal": "first_parent",
            "maximum_commits": max_commits,
            "pairs_scanned": len(pairs),
            "modified_lean_files_considered": files_considered,
            "candidate_rule": "same parsed declaration header; proof changed in window; endpoint proof differs",
        },
        "candidates": candidates,
    }


def screen_inventory(
    repo: Path,
    inventory: dict[str, Any],
    *,
    project_root: Path | None,
    timeout: float,
    completed: dict[str, dict[str, Any]] | None = None,
    on_decision: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """逐项执行真实修复门禁，并为每个排除项保存明确理由。"""

    if inventory.get("version") != INVENTORY_VERSION:
        raise ValueError("候选清单版本不匹配")
    spec_base = {
        "version": PROTOCOL_VERSION,
        "benchmark_version": f"tracer-real-{inventory['project_id']}-v2",
        "source_repository": inventory["source_repository"],
        "source_license": inventory["source_license"],
    }
    accepted: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    completed = completed or {}
    for candidate in inventory.get("candidates", []):
        item = {key: candidate[key] for key in ("id", "before_revision", "fixed_revision", "file", "theorem")}
        decision = completed.get(item["id"])
        if decision is not None:
            if decision.get("candidate") != item:
                raise ValueError("续跑状态中的候选内容与冻结清单不一致：" + item["id"])
            outcome = decision.get("outcome")
            if not isinstance(outcome, dict) or outcome.get("id") != item["id"]:
                raise ValueError("续跑状态中的筛查结果损坏：" + item["id"])
        else:
            try:
                problem, _ = build_case(repo.resolve(), spec_base, item, timeout, project_root)
            except (ValueError, OSError) as error:
                outcome = {"id": item["id"], "accepted": False, "reason": str(error)}
            else:
                outcome = {
                    "id": item["id"],
                    "accepted": True,
                    "error_category": problem["expected_error"],
                }
            decision = {"candidate": item, "outcome": outcome}
            if on_decision is not None:
                on_decision(decision)
        decisions.append(outcome)
        if outcome.get("accepted") is True:
            accepted.append(item)
    spec = {**spec_base, "cases": accepted}
    report = {
        "version": SCREEN_VERSION,
        "project_id": inventory["project_id"],
        "endpoint_revision": inventory["endpoint_revision"],
        "provider_calls_observed": 0,
        "candidates": len(inventory.get("candidates", [])),
        "accepted": len(accepted),
        "rejected": len(decisions) - len(accepted),
        "decisions": decisions,
        "selection_policy": "all candidates passing the preregistered real-repair compile gate",
    }
    return spec, report


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON 顶层必须是对象")
    return value


def _load_screen_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or set(value) != {"candidate", "outcome"}:
            raise ValueError(f"筛查续跑状态第 {line_no} 行格式错误")
        candidate = value.get("candidate")
        if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
            raise ValueError(f"筛查续跑状态第 {line_no} 行缺少候选 ID")
        candidate_id = candidate["id"]
        if candidate_id in completed:
            raise ValueError("筛查续跑状态含重复候选：" + candidate_id)
        completed[candidate_id] = value
    return completed


def _append_screen_state(path: Path, decision: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(decision, ensure_ascii=False) + "\n")
        stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="确定性发现并筛查 Lean 真实证明修复候选")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="固定端点和历史窗口，枚举纯证明变化；不运行 Lean")
    scan.add_argument("--repo", type=Path, required=True)
    scan.add_argument("--project-id", required=True)
    scan.add_argument("--source-repository", required=True)
    scan.add_argument("--source-license", required=True)
    scan.add_argument("--endpoint", default="HEAD")
    scan.add_argument("--max-commits", type=int, default=120)
    scan.add_argument("--out", type=Path, required=True)
    screen = sub.add_parser("screen", help="逐项执行旧证明失败、新证明通过门禁")
    screen.add_argument("--repo", type=Path, required=True)
    screen.add_argument("--inventory", type=Path, required=True)
    screen.add_argument("--project-root", type=Path)
    screen.add_argument("--timeout", type=float, default=180)
    screen.add_argument("--state", type=Path, required=True)
    screen.add_argument("--spec-out", type=Path, required=True)
    screen.add_argument("--report-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "scan":
            result = scan_history(
                args.repo,
                project_id=args.project_id,
                source_repository=args.source_repository,
                source_license=args.source_license,
                endpoint=args.endpoint,
                max_commits=args.max_commits,
            )
            write_json(args.out, result)
            print(json.dumps({
                "ok": True,
                "project_id": result["project_id"],
                "candidates": len(result["candidates"]),
                "network_calls": 0,
            }, ensure_ascii=False))
        else:
            if args.spec_out.exists() or args.report_out.exists():
                raise ValueError("输出已存在；拒绝覆盖候选筛查记录")
            completed = _load_screen_state(args.state)
            spec, report = screen_inventory(
                args.repo,
                _read_json(args.inventory),
                project_root=args.project_root.resolve() if args.project_root else None,
                timeout=args.timeout,
                completed=completed,
                on_decision=lambda value: _append_screen_state(args.state, value),
            )
            write_json(args.spec_out, spec)
            write_json(args.report_out, report)
            print(json.dumps({
                "ok": True,
                "project_id": report["project_id"],
                "candidates": report["candidates"],
                "accepted": report["accepted"],
                "rejected": report["rejected"],
                "network_calls": 0,
            }, ensure_ascii=False))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
