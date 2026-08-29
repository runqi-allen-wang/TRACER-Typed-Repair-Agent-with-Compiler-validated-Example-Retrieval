"""在新回放副本内从本地公开 Git 依赖复制固定修订；不复制平台构建目录。"""
import argparse
import json
import subprocess
from pathlib import Path


def copy_dependencies(source_project, destination_project):
    manifest = json.loads((destination_project / "lake-manifest.json").read_text(encoding="utf-8"))
    base = destination_project / ".lake/packages"
    base.mkdir(parents=True, exist_ok=False)
    for package in manifest["packages"]:
        if package["type"] != "git" or not package["name"].replace("_", "").isalnum():
            raise ValueError("只复制清单中命名明确的 Git 依赖")
        source = (source_project / ".lake/packages" / package["name"]).resolve()
        target = base / package["name"]
        subprocess.run(["git", "-c", "safe.directory=" + str(source), "clone", "--no-hardlinks", "--no-checkout", str(source), str(target)], check=True)
        subprocess.run(["git", "-C", str(target), "remote", "set-url", "origin", package["url"]], check=True)
        subprocess.run(["git", "-C", str(target), "checkout", "--detach", package["rev"]], check=True)
        print("已准备固定源码：" + package["name"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project", type=Path, required=True)
    parser.add_argument("--destination-project", type=Path, required=True)
    args = parser.parse_args()
    copy_dependencies(args.source_project.resolve(), args.destination_project.resolve())
