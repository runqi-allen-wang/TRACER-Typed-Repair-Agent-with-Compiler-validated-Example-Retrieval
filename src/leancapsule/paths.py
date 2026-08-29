"""LeanCapsule 路径解析与仓库边界检查。"""

from __future__ import annotations

from pathlib import Path


def is_within(path: Path, root: Path) -> bool:
    """返回解析后的 path 是否位于 root 内（包含 root 本身）。"""

    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def find_repository_root(path: Path) -> Path | None:
    """寻找包含仓库 CLI 与实现包的最近祖先目录。"""

    resolved = path.resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    for parent in (start, *start.parents):
        if (parent / "leancapsule" / "__main__.py").is_file() and (parent / "src" / "leancapsule").is_dir():
            return parent
    return None


def resolve_capsule_file(capsule: Path, value: str, field: str = "replay.file") -> Path:
    """解析必须位于 capsule 内的相对文件路径。"""

    raw = Path(value)
    if raw.is_absolute():
        raise ValueError(f"{field} 必须是 capsule 内的相对路径")
    resolved = (capsule.resolve() / raw).resolve()
    if not is_within(resolved, capsule):
        raise ValueError(f"{field} 不能逃逸 capsule 目录")
    return resolved


def resolve_dependency_project(capsule: Path, value: str | None) -> Path:
    """解析依赖项目；仓库内 capsule 可引用同仓库的共享依赖工程。"""

    capsule = capsule.resolve()
    if not value:
        return capsule
    raw = Path(value)
    if raw.is_absolute():
        raise ValueError("environment.dependency_project 必须是相对路径")
    resolved = (capsule / raw).resolve()
    repository_root = find_repository_root(capsule)
    allowed_root = repository_root or capsule
    if not is_within(resolved, allowed_root):
        raise ValueError("environment.dependency_project 不能逃逸仓库或 capsule 目录")
    return resolved
