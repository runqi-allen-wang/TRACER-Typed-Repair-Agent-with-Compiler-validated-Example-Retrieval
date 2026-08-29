"""运行完整测试，并把失败详情写入 GitHub Actions 摘要。"""

from __future__ import annotations

import io
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    rendered = output.getvalue()
    print(rendered, end="")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        status = "通过" if result.wasSuccessful() else "失败"
        # 摘要保留末尾错误栈，避免公开运行只显示无上下文的退出码。
        excerpt = rendered[-12000:]
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(f"## Python 测试：{status}\n\n")
            handle.write("```text\n")
            handle.write(excerpt)
            handle.write("\n```\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
