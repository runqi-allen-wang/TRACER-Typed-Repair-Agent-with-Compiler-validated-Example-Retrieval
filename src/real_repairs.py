"""从公开 Git 历史中的旧证明/新证明对构建真实 Lean 修复任务。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from compiler import compile_candidate, declaration_scope, diagnostics_use_sorry
from compiler_feedback import build_feedback_record
from diagnostics import normalize_diagnostics
from research import load_benchmark, write_json


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "tracer-real-repair-v1"
PROJECT_SPLIT_VERSION = "tracer-real-project-split-v1"
PROJECT_SPLIT_VERSION_V2 = "tracer-real-project-split-v2"
PROJECT_SPLITS = ("development", "validation", "test")


def _canonical_repository(value: str) -> str:
    parsed = urlsplit(value)
    path = parsed.path.rstrip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    return parsed.netloc.lower() + path.lower()


def _git(repo: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
    )
    if process.returncode != 0:
        raise ValueError((process.stderr or process.stdout).strip() or "Git 命令失败")
    return process.stdout


def _resolve_revision(repo: Path, revision: str) -> str:
    if not revision or any(character.isspace() for character in revision):
        raise ValueError("版本引用不能为空或包含空白")
    return _git(repo, "rev-parse", "--verify", revision + "^{commit}").strip()


def _git_file(repo: Path, revision: str, relative_path: str) -> str:
    path = Path(relative_path)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("源码路径必须是仓库内相对路径")
    return _git(repo, "show", f"{revision}:{path.as_posix()}")


def _proof_delimiter(scope: str) -> int:
    """寻找声明最外层的 ``:=``，忽略注释和字符串。"""

    index = 0
    block_depth = 0
    in_string = False
    escaped = False
    nesting = 0
    while index < len(scope) - 1:
        current, following = scope[index], scope[index + 1]
        if block_depth:
            if current == "/" and following == "-":
                block_depth += 1
                index += 2
                continue
            if current == "-" and following == "/":
                block_depth -= 1
                index += 2
                continue
            index += 1
            continue
        if not in_string and current == "-" and following == "-":
            newline = scope.find("\n", index + 2)
            index = len(scope) if newline < 0 else newline + 1
            continue
        if not in_string and current == "/" and following == "-":
            block_depth = 1
            index += 2
            continue
        if in_string:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                in_string = False
            index += 1
            continue
        if current == '"':
            in_string = True
            index += 1
            continue
        if current in "([{":
            nesting += 1
            index += 1
            continue
        if current in ")]}":
            nesting = max(0, nesting - 1)
            index += 1
            continue
        if nesting == 0 and current == ":" and following == "=":
            return index
        index += 1
    raise ValueError("目标声明缺少可定位的证明分隔符")


def declaration_parts(source: str, theorem_name: str) -> dict[str, Any]:
    start, end = declaration_scope(source, theorem_name)
    scope = source[start:end]
    delimiter = _proof_delimiter(scope)
    return {
        "scope_start": start,
        "scope_end": end,
        "header": scope[:delimiter].strip(),
        "proof": scope[delimiter + 2:].strip(),
        "delimiter": start + delimiter,
    }


def _normalized_header(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def marked_source(fixed_source: str, theorem_name: str, historical_proof: str) -> str:
    parts = declaration_parts(fixed_source, theorem_name)
    left = fixed_source[:parts["delimiter"] + 2].rstrip()
    right = fixed_source[parts["scope_end"]:]
    return (
        left + "\n  -- PROOF_START\n  " + historical_proof.strip()
        + "\n  -- PROOF_END\n\n" + right.lstrip("\r\n")
    )


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("version") != PROTOCOL_VERSION:
        raise ValueError("真实修复任务规范版本不匹配")
    required_top = {"version", "benchmark_version", "source_repository", "source_license", "cases"}
    if set(spec) != required_top:
        raise ValueError("真实修复任务规范顶层字段不完整")
    if not spec["benchmark_version"] or not spec["source_repository"] or not spec["source_license"]:
        raise ValueError("基准版本、公开来源和许可不能为空")
    repository = urlsplit(str(spec["source_repository"]))
    if (
        repository.scheme != "https" or not repository.netloc
        or repository.username or repository.password or repository.query or repository.fragment
    ):
        raise ValueError("公开来源必须是无凭据、无查询参数的 HTTPS 仓库地址")
    if not isinstance(spec["cases"], list) or not spec["cases"]:
        raise ValueError("至少需要一个真实修复候选")
    ids = set()
    required = {"id", "before_revision", "fixed_revision", "file", "theorem"}
    for item in spec["cases"]:
        if set(item) != required:
            raise ValueError("真实修复候选字段不完整")
        if not re.fullmatch(r"[a-z0-9_]+", item["id"]) or item["id"] in ids:
            raise ValueError("真实修复任务 ID 非法或重复")
        ids.add(item["id"])


def build_case(
    repo: Path,
    spec: dict[str, Any],
    item: dict[str, Any],
    timeout: float,
    project_root: Path | None = None,
) -> tuple[dict[str, Any], str]:
    before_revision = _resolve_revision(repo, item["before_revision"])
    fixed_revision = _resolve_revision(repo, item["fixed_revision"])
    current_revision = _resolve_revision(repo, "HEAD")
    if current_revision != fixed_revision:
        raise ValueError(f"{item['id']}: 本地源码必须检出到 fixed_revision 后再构建")

    before_source = _git_file(repo, before_revision, item["file"])
    fixed_source = _git_file(repo, fixed_revision, item["file"])
    source_path = (repo / item["file"]).resolve()
    if not source_path.is_file() or source_path.read_text(encoding="utf-8") != fixed_source:
        raise ValueError(f"{item['id']}: 工作树源码与固定版本不一致")
    before_parts = declaration_parts(before_source, item["theorem"])
    fixed_parts = declaration_parts(fixed_source, item["theorem"])
    if _normalized_header(before_parts["header"]) != _normalized_header(fixed_parts["header"]):
        raise ValueError(f"{item['id']}: 定理陈述发生变化，不属于纯证明修复")
    if before_parts["proof"] == fixed_parts["proof"]:
        raise ValueError(f"{item['id']}: 两个版本的证明没有变化")

    task_source = marked_source(fixed_source, item["theorem"], before_parts["proof"])
    compile_anchor = (
        project_root / f"TRACERRealRepair_{item['id']}.lean"
        if project_root is not None else source_path
    )
    failed = compile_candidate(
        compile_anchor, task_source, before_parts["proof"], item["theorem"], timeout=timeout,
    )
    diagnostic = normalize_diagnostics(
        failed.diagnostics, returncode=failed.returncode, timed_out=failed.timed_out,
    )
    if failed.ok or failed.timed_out or failed.returncode is None:
        raise ValueError(
            f"{item['id']}: 历史证明没有形成稳定的 Lean 证明失败 "
            f"(ok={failed.ok}, timed_out={failed.timed_out}, returncode={failed.returncode})"
        )
    fixed = compile_candidate(
        compile_anchor, task_source, fixed_parts["proof"], item["theorem"], timeout=timeout,
    )
    if not fixed.ok or diagnostics_use_sorry(fixed.diagnostics):
        raise ValueError(f"{item['id']}: 修复后证明不能独立通过当前固定环境")

    feedback = build_feedback_record(
        case_id=item["id"], diagnostic_text=failed.diagnostics, compile_ok=False,
        returncode=failed.returncode, round_no=1, roots=(repo,),
    )
    problem = {
        "id": item["id"],
        "file": f"tasks/{item['id']}.lean",
        "theorem": item["theorem"],
        "tags": ["real_history", feedback["structured"]["category"]],
        "difficulty": "natural-contextual-repair",
        "expected_error": feedback["structured"]["category"],
        "source_text": task_source,
        "provenance": {
            "source_repository": spec["source_repository"],
            "source_license": spec["source_license"],
            "before_revision": before_revision,
            "fixed_revision": fixed_revision,
            "source_file": item["file"],
            "construction": "historical_proof_in_fixed_context",
            "statement_unchanged": True,
            "initial_failure_reproduced": True,
            "fixed_proof_recompiled": True,
            "compile_environment": "specified_lake_project" if project_root else "source_repository_checkout",
        },
        "initial_feedback": feedback,
    }
    return problem, fixed_parts["proof"]


def build_benchmark(
    repo: Path,
    spec_path: Path,
    out: Path,
    reference_out: Path,
    timeout: float = 120,
    project_root: Path | None = None,
) -> dict[str, Any]:
    repo, out, reference_out = repo.resolve(), out.resolve(), reference_out.resolve()
    if project_root is not None:
        project_root = project_root.resolve()
        if not ((project_root / "lakefile.toml").is_file() or (project_root / "lakefile.lean").is_file()):
            raise ValueError("显式编译项目根缺少 lakefile")
    if out == reference_out or out in reference_out.parents or reference_out in out.parents:
        raise ValueError("公开任务目录与隔离参考证明目录必须彼此独立")
    if out.exists() or reference_out.exists():
        raise ValueError("输出目录已存在；拒绝覆盖旧基准或参考证明")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    validate_spec(spec)
    cases = [build_case(repo, spec, item, timeout, project_root) for item in spec["cases"]]
    toolchain_path = (project_root or repo) / "lean-toolchain"
    manifest = {
        "version": spec["benchmark_version"],
        "status": "frozen-real-history",
        "license": spec["source_license"],
        "description": "公开版本历史中的旧证明在固定后续上下文中失败、对应修复证明通过；参考证明与运行题库隔离。",
        "lean_toolchain": toolchain_path.read_text(encoding="utf-8").strip() if toolchain_path.is_file() else "not-recorded",
        "problems": [problem for problem, _ in cases],
    }
    out.mkdir(parents=True)
    reference_out.mkdir(parents=True)
    for problem, reference in cases:
        path = out / problem["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(problem["source_text"], encoding="utf-8")
        (reference_out / f"{problem['id']}.txt").write_text(reference + "\n", encoding="utf-8")
    write_json(out / "manifest.json", manifest)
    write_json(reference_out / "validation.json", {
        "protocol_version": PROTOCOL_VERSION,
        "benchmark_version": spec["benchmark_version"],
        "case_ids": [problem["id"] for problem, _ in cases],
        "release_policy": "参考证明不得放入模型提示、检索语料或公开任务目录。",
    })
    return {"ok": True, "benchmark": manifest["version"], "tasks": len(cases), "out": str(out), "reference_out": str(reference_out)}


def assemble_project_benchmark(spec_path: Path, out: Path) -> dict[str, Any]:
    """把彼此独立的上游项目子集组合为项目级隔离的公开题库。"""

    spec_path, out = spec_path.resolve(), out.resolve()
    if out.exists():
        raise ValueError("输出目录已存在；拒绝覆盖已冻结的项目级题库")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    required_top = {"version", "benchmark_version", "split_policy", "projects"}
    if set(spec) != required_top or spec.get("version") not in {PROJECT_SPLIT_VERSION, PROJECT_SPLIT_VERSION_V2}:
        raise ValueError("项目级题库规范版本或顶层字段不匹配")
    is_v2 = spec["version"] == PROJECT_SPLIT_VERSION_V2
    if spec.get("split_policy") != "upstream_project_disjoint":
        raise ValueError("TRACER-REAL 必须按上游项目完全隔离")
    projects = spec.get("projects")
    if not isinstance(projects, list) or len(projects) < 3:
        raise ValueError("项目级题库至少需要三个独立上游项目")

    project_ids: set[str] = set()
    source_repositories: set[str] = set()
    seen_splits: set[str] = set()
    problem_ids: set[str] = set()
    project_rows = []
    project_environments = []
    problems = []
    source_rows: list[tuple[Path, Path]] = []
    for project in projects:
        expected_project_fields = (
            {"project_id", "split", "manifest", "compile_project_root", "lean_toolchain"}
            if is_v2 else {"project_id", "split", "manifest"}
        )
        if set(project) != expected_project_fields:
            raise ValueError("项目级题库项目字段不完整")
        project_id, split = project["project_id"], project["split"]
        if not re.fullmatch(r"[a-z0-9_]+", project_id) or project_id in project_ids:
            raise ValueError("项目 ID 非法或重复")
        if split not in PROJECT_SPLITS:
            raise ValueError("项目划分只能是 development、validation 或 test")
        project_ids.add(project_id)
        seen_splits.add(split)
        manifest_path = (spec_path.parent / project["manifest"]).resolve()
        manifest = load_benchmark(manifest_path)
        repositories = {
            item.get("provenance", {}).get("source_repository") for item in manifest["problems"]
        }
        if len(repositories) != 1 or None in repositories:
            raise ValueError(f"{project_id}: 子集缺少唯一公开上游项目")
        canonical_repository = _canonical_repository(str(next(iter(repositories))))
        if canonical_repository in source_repositories:
            raise ValueError("同一上游仓库不得以多个项目身份重复进入题库")
        source_repositories.add(canonical_repository)
        project_rows.append({
            "project_id": project_id,
            "split": split,
            "source_benchmark_version": manifest["version"],
            "source_repository": next(iter(repositories)),
            "tasks": len(manifest["problems"]),
        })
        if is_v2:
            compile_root_value = project["compile_project_root"]
            compile_root_path = Path(compile_root_value)
            if compile_root_path.is_absolute() or not compile_root_path.parts or ".." in compile_root_path.parts:
                raise ValueError(f"{project_id}: 编译项目根必须是仓库内相对路径")
            compile_root = (ROOT / compile_root_path).resolve()
            try:
                compile_root.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise ValueError(f"{project_id}: 编译项目根逃逸仓库") from exc
            if not ((compile_root / "lakefile.toml").is_file() or (compile_root / "lakefile.lean").is_file()):
                raise ValueError(f"{project_id}: 编译项目根缺少 lakefile")
            toolchain_path = compile_root / "lean-toolchain"
            if not toolchain_path.is_file():
                raise ValueError(f"{project_id}: 编译项目根缺少 lean-toolchain")
            toolchain = toolchain_path.read_text(encoding="utf-8").strip()
            if toolchain != project["lean_toolchain"]:
                raise ValueError(f"{project_id}: lean-toolchain 与冻结规范不一致")
            project_environments.append({
                "project_id": project_id,
                "project_root": compile_root_path.as_posix(),
                "lean_toolchain": toolchain,
            })
        for problem in manifest["problems"]:
            if problem["id"] in problem_ids:
                raise ValueError("跨项目题目 ID 重复：" + problem["id"])
            problem_ids.add(problem["id"])
            relative = Path("tasks") / project_id / f"{problem['id']}.lean"
            row = {
                **problem,
                "file": relative.as_posix(),
                "project_id": project_id,
                "split": split,
                "source_benchmark_version": manifest["version"],
            }
            problems.append(row)
            source_rows.append((manifest_path.parent / problem["file"], relative))
    if seen_splits != set(PROJECT_SPLITS):
        raise ValueError("项目级题库必须同时冻结 development、validation 和 test")

    out.mkdir(parents=True)
    for source, relative in source_rows:
        destination = out / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = {
        "version": spec["benchmark_version"],
        "status": "frozen-project-disjoint-real-history",
        "license": "Each task retains the upstream license recorded in provenance.",
        "description": "真实公开 Git 历史修复对；开发、验证、测试按上游项目完全隔离。",
        "lean_toolchain": (
            "per-project-frozen-in-project_environments"
            if is_v2 else
            (ROOT / "mathlib_project/lean-toolchain").read_text(encoding="utf-8").strip()
        ),
        "split_policy": spec["split_policy"],
        "projects": project_rows,
        "problems": problems,
    }
    if is_v2:
        manifest["project_environments"] = project_environments
    write_json(out / "manifest.json", manifest)
    # 再经通用题库加载器核对文件内容、路径和局部证明区域。
    load_benchmark(out / "manifest.json")
    return {
        "ok": True,
        "benchmark": manifest["version"],
        "projects": len(project_rows),
        "tasks": len(problems),
        "splits": {split: sum(row["tasks"] for row in project_rows if row["split"] == split) for split in PROJECT_SPLITS},
        "out": str(out),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--repo", type=Path, required=True)
    build.add_argument("--spec", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--reference-out", type=Path, required=True)
    build.add_argument("--project-root", type=Path)
    build.add_argument("--timeout", type=float, default=120)
    assemble = sub.add_parser("assemble-projects")
    assemble.add_argument("--spec", type=Path, required=True)
    assemble.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build_benchmark(
                args.repo, args.spec, args.out, args.reference_out, args.timeout, args.project_root,
            )
        else:
            result = assemble_project_benchmark(args.spec, args.out)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
