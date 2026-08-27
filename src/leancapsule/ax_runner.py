"""Run the pinned AxProverBase CLI with Part 2 CapsuleFeedback installed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .ax_integration import install_axproverbase_capsule_feedback


def main(argv: list[str] | None = None) -> None:
    if argv is not None:
        sys.argv = [sys.argv[0], *argv]
    default_config = Path(__file__).resolve().parents[2] / "configs" / "axprover_part2_capsule.yaml"
    config = Path(os.environ.get("CAPSULE_AX_CONFIG", default_config)).resolve()
    if not config.is_file():
        raise SystemExit(f"Part 2 Ax config not found: {config}")
    sys.argv[1:1] = ["--config", os.fspath(config)]
    install_axproverbase_capsule_feedback()
    from ax_prover.main import main as ax_main

    ax_main()


if __name__ == "__main__":
    main()
