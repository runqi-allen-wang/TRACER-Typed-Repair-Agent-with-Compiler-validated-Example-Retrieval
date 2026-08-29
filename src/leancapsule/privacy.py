"""公开 Capsule 输出中的路径与敏感信息清理。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


WINDOWS_ABSOLUTE = re.compile(r"[A-Za-z]:[\\/][^\s\"']+")
POSIX_ABSOLUTE = re.compile(r"/(?:home|Users|tmp|private|var/tmp)/[^\s\"']+")


def redact_text(text: str, roots: tuple[Path, ...] = ()) -> str:
    cleaned = text
    for root in roots:
        cleaned = cleaned.replace(str(root), "<workspace>")
        cleaned = cleaned.replace(str(root).replace("\\", "/"), "<workspace>")
    cleaned = WINDOWS_ABSOLUTE.sub("<local-path>", cleaned)
    cleaned = POSIX_ABSOLUTE.sub("<local-path>", cleaned)
    return cleaned


def redact_value(value: Any, roots: tuple[Path, ...] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, roots)
    if isinstance(value, list):
        return [redact_value(item, roots) for item in value]
    if isinstance(value, dict):
        return {key: redact_value(item, roots) for key, item in value.items()}
    return value
