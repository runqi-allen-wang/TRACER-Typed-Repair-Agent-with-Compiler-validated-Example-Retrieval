"""按当前生成器刷新所有公开 Capsule 的跨目录回放脚本。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leancapsule.pack import _write_scripts


def main() -> int:
    capsules = sorted(path.parent for path in (ROOT / "capsules").rglob("capsule.json"))
    for capsule in capsules:
        _write_scripts(capsule)
    print(f"已刷新 {len(capsules)} 个 Capsule 回放脚本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

