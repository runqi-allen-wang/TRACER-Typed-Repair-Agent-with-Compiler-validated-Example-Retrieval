"""Validate the exact AxProverBase source contract consumed by Part 2."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from pathlib import Path


EXPECTED_COMMIT = "06dfadc9ab439755af5efcfe0add95bfef2733c7"


def _class(tree: ast.Module, name: str) -> ast.ClassDef | None:
    return next(
        (node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name),
        None,
    )


def _method(class_node: ast.ClassDef | None, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    if class_node is None:
        return None
    return next(
        (
            node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ),
        None,
    )


def _called_name(call: ast.Call) -> str:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def validate_axprover_source(root: Path, *, expected_commit: str | None = EXPECTED_COMMIT) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    package = root / "src" / "ax_prover"
    if not package.is_dir() and (root / "ax_prover").is_dir():
        package = root / "ax_prover"

    if expected_commit is not None:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        actual = completed.stdout.strip()
        if completed.returncode != 0:
            errors.append("cannot read AxProverBase git commit")
        elif actual != expected_commit:
            errors.append(f"AxProverBase commit mismatch: expected {expected_commit}, got {actual}")

    required = {
        "agent": package / "prover" / "agent.py",
        "messages": package / "models" / "messages.py",
        "memory": package / "prover" / "memory.py",
        "config": package / "config.py",
    }
    for label, path in required.items():
        if not path.is_file():
            errors.append(f"missing AxProverBase {label} source: {path}")
    if errors:
        return errors

    agent_tree = ast.parse(required["agent"].read_text(encoding="utf-8"))
    agent_class = _class(agent_tree, "ProverAgent")
    builder = _method(agent_class, "_builder_node")
    if builder is None:
        errors.append("ProverAgent._builder_node is missing")
    else:
        check_calls = [
            node
            for node in ast.walk(builder)
            if isinstance(node, ast.Call) and _called_name(node) == "check_lean_file"
        ]
        if len(check_calls) != 1:
            errors.append(
                f"expected exactly one check_lean_file call in _builder_node, found {len(check_calls)}"
            )
        source = ast.get_source_segment(required["agent"].read_text(encoding="utf-8"), builder) or ""
        for required_name in (
            "BuildFailedFeedback",
            "BuildSuccessFeedback",
            "SorriesGoalStateFeedback",
        ):
            if required_name not in source:
                errors.append(f"_builder_node no longer uses {required_name}")

    message_tree = ast.parse(required["messages"].read_text(encoding="utf-8"))
    for class_name in (
        "FeedbackMessage",
        "BuildFailedFeedback",
        "BuildSuccessFeedback",
        "SorriesGoalStateFeedback",
    ):
        if _class(message_tree, class_name) is None:
            errors.append(f"Ax message class is missing: {class_name}")

    memory_tree = ast.parse(required["memory"].read_text(encoding="utf-8"))
    if _class(memory_tree, "MemorylessProcessor") is None:
        errors.append("Ax MemorylessProcessor is missing")

    config_text = required["config"].read_text(encoding="utf-8")
    for field_name in ("prover_llm", "memory_config", "summarize_output"):
        if field_name not in config_text:
            errors.append(f"Ax ProverConfig field is missing: {field_name}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True, help="AxProverBase checkout/package root")
    parser.add_argument("--expected-commit", default=EXPECTED_COMMIT)
    parser.add_argument("--skip-git-check", action="store_true")
    args = parser.parse_args(argv)
    errors = validate_axprover_source(
        args.source,
        expected_commit=None if args.skip_git_check else args.expected_commit,
    )
    print(
        json.dumps(
            {
                "ok": not errors,
                "expected_commit": args.expected_commit,
                "source": str(args.source.resolve()),
                "errors": errors,
            },
            ensure_ascii=False,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
