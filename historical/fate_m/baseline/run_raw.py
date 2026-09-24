"""Run the Part 3 Raw Memoryless condition through the shared runner."""

from __future__ import annotations

import sys

from run_part2 import main as _run_feedback


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--feedback" not in args:
        args.extend(["--feedback", "raw"])
    return _run_feedback(args)


if __name__ == "__main__":
    raise SystemExit(main())
