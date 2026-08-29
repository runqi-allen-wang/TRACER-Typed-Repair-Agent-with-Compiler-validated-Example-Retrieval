"""将仓库 PowerShell 脚本统一写成 Windows PowerShell 5.1 可识别的 UTF-8 BOM。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    paths = sorted(path for path in ROOT.rglob("*.ps1") if ".lake" not in path.parts)
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        path.write_text(text, encoding="utf-8-sig")
    print(f"已规范化 {len(paths)} 个 PowerShell 脚本")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
