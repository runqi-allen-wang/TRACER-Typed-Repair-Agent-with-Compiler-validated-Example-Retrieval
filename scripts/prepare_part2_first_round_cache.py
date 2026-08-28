"""Convert Part 1 metrics JSONL into an exact Ax target candidate cache."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


_DECLARATION_RE = re.compile(r"\b(?:theorem|lemma|def|instance|example|opaque|abbrev)\b")


def _canonical_target(module: str, theorem: str) -> str:
    module = module.strip().replace("\\", "/")
    while module.startswith("./"):
        module = module[2:]
    if module.endswith(".lean"):
        module = module[: -len(".lean")]
    module = module.replace("/", ".").strip(".")
    theorem = theorem.strip()
    if not module or not theorem:
        raise ValueError("module/theorem is required")
    return f"{module}:{theorem}"


def prepare_cache(rows: list[dict]) -> dict[str, dict]:
    cache: dict[str, dict] = {}
    for row_no, row in enumerate(rows, start=1):
        condition = str(row.get("condition") or "").lower()
        if condition not in {"baseline", "experience"}:
            continue
        theorem = str(row.get("theorem") or "")
        run_target = str(row.get("target") or "")
        target_suffix = f":{theorem}"
        if theorem and run_target.endswith(target_suffix):
            module = run_target[: -len(target_suffix)]
        else:
            module = str(row.get("module") or "").replace("/", ".").removesuffix(".lean")
        candidate = str(row.get("first_round_candidate") or "")
        if not module or not theorem:
            raise ValueError(f"row {row_no}: module/theorem is required")
        if not candidate.strip():
            raise ValueError(f"row {row_no}: first_round_candidate is empty")
        if not _DECLARATION_RE.search(candidate):
            raise ValueError(
                f"row {row_no}: first_round_candidate must contain the complete declaration"
            )
        imports = row.get("first_round_imports") or []
        opens = row.get("first_round_opens") or []
        if isinstance(imports, str) or not isinstance(imports, list):
            raise ValueError(f"row {row_no}: first_round_imports must be a list")
        if isinstance(opens, str) or not isinstance(opens, list):
            raise ValueError(f"row {row_no}: first_round_opens must be a list")
        target = _canonical_target(module, theorem)
        payload = {
            "code": candidate,
            "reasoning": str(row.get("first_round_reasoning") or "Reused Part 1 candidate."),
            "imports": imports,
            "opens": opens,
        }
        previous = cache.get(target)
        if previous is not None and previous != payload:
            raise ValueError(f"conflicting first-round candidates for {target}")
        cache[target] = payload
    if not cache:
        raise ValueError("no baseline/experience first-round candidates found")
    return cache


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_no} must be a JSON object")
        rows.append(value)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        cache = prepare_cache(_read_jsonl(args.baseline))
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "entries": len(cache), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
