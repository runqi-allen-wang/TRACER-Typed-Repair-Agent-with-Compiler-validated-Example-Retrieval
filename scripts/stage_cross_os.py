"""创建仅含公开源码的独立回放副本；不复制凭据、历史实验或平台构建物。"""
import argparse
import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("src", "leancapsule", "capsules", "capsule_schema", "gallery_sources", "lean_project", "examples")
FILES = ("lean-toolchain", "lakefile.toml", "lake-manifest.json", "requirements.txt",
         "mathlib_project/lean-toolchain", "mathlib_project/lakefile.lean",
         "mathlib_project/lake-manifest.json", "experiments/capsule_sources.json")
EXTENSIONS = {".py", ".lean", ".json", ".toml", ".md", ".txt", ".csv", ".sh", ".ps1"}


def stage(source, destination):
    source, destination = source.resolve(), destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    paths = [source / name for name in FILES if (source / name).is_file()]
    for name in DIRECTORIES:
        for directory, children, files in os.walk(source / name, followlinks=False):
            children[:] = [child for child in children if not child.startswith(".") and child != "__pycache__"]
            for filename in files:
                path = Path(directory) / filename
                if path.suffix in EXTENSIONS or path.name == "lean-toolchain":
                    paths.append(path)
    entries = []
    for path in sorted(set(paths)):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("副本拒绝链接或越界文件")
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if path.read_bytes() != target.read_bytes():
            raise ValueError("副本与原始文件直接比较不一致")
        entries.append({"path": relative.as_posix(), "bytes": target.stat().st_size})
    (destination / "staging.json").write_text(json.dumps({"files": entries,
        "comparison": "逐文件完整字节相等", "build_artifacts_copied": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"files": stage(args.source, args.out)}))
