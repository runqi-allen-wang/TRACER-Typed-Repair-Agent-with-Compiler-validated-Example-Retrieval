"""支持在仓库根目录运行 python -m leancapsule。"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from src.leancapsule.cli import main

raise SystemExit(main())
