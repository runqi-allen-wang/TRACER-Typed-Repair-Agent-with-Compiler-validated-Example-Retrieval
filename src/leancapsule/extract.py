"""从 Lean 文件中提取可尝试独立编译的定理片段。"""

from __future__ import annotations

import re

from compiler import declaration_scope


IMPORT_RE = re.compile(r"(?m)^\s*import\s+[^\r\n]+$")
NAMESPACE_RE = re.compile(r"(?m)^namespace\s+([A-Za-z_][A-Za-z0-9_.]*)\s*$")


def _namespace_for(source: str, position: int) -> str | None:
    matches = list(NAMESPACE_RE.finditer(source[:position]))
    return matches[-1].group(1) if matches else None


def extract_theorem(source: str, theorem: str) -> str:
    """保留 imports、目标定理和外层 namespace，供后续编译验证。"""

    start, end = declaration_scope(source, theorem)
    imports = "\n".join(match.group(0).strip() for match in IMPORT_RE.finditer(source))
    namespace = _namespace_for(source, start)
    body = source[start:end].strip()
    parts = [part for part in (imports, f"namespace {namespace}" if namespace else "", body, f"end {namespace}" if namespace else "") if part]
    return "\n\n".join(parts) + "\n"
