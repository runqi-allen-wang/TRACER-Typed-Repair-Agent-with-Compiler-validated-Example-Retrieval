"""批量验证 capsule 目录。"""

from __future__ import annotations

from pathlib import Path

from .replay import replay_capsule


def verify_directory(root: Path, timeout: float = 180.0) -> dict:
    """递归寻找 capsule.json，返回逐项与汇总状态。"""

    capsules = sorted({path.parent for path in root.rglob("capsule.json")})
    results = [replay_capsule(path, timeout=timeout) for path in capsules]
    passed = sum(1 for result in results if result.get("ok"))
    return {"ok": passed == len(results), "total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}
