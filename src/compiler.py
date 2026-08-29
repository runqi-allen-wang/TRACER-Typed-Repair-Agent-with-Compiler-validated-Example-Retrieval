"""通用 Lean 源码补丁与内核编译。"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
import os
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DECLARATION_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?P<kind>theorem|lemma)[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_']*)\b"
)
COMMAND_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?:theorem|lemma|def|abbrev|instance|structure|class|inductive|"
    r"coinductive|axiom|opaque|example|namespace|section|end|variable|include|omit|open|attribute|"
    r"set_option)\b"
)
SCOPE_RE = re.compile(
    r"(?m)^[ \t]*(?P<kind>namespace|section|end)(?:[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_'.]*))?"
    r"[ \t]*(?:--.*)?$"
)
PLACEHOLDER_RE = re.compile(r"\b(?:sorryAx|sorry|admit)\b")
SORRY_WARNING_RE = re.compile(r"declaration uses[^\r\n]*\bsorry\b", re.IGNORECASE)
_SAFE_ENVIRONMENT_NAMES = {
    "APPDATA", "COMSPEC", "ELAN_HOME", "HOME", "HOMEDRIVE", "HOMEPATH",
    "LANG", "LOCALAPPDATA", "PATH", "PATHEXT", "SYSTEMDRIVE", "SYSTEMROOT",
    "TEMP", "TMP", "USERPROFILE", "WINDIR",
}
_UNSAFE_ELABORATION = re.compile(
    r"(?ix)(?<![A-Za-z0-9_'])\b(?:run_tac|run_term_elab|eval_tac|elab_rules|macro_rules|native_decide)\b"
    r"|(?<![A-Za-z0-9_'])\bunsafe\b|\#(?:[A-Za-z_][A-Za-z0-9_']*)"
    r"|\b(?:IO|System|Process|Lean\.Elab|Lean\.Parser)\s*\."
    r"|\b(?:readFile|writeFile|getEnv|spawn|execute|include_str)\b"
)
_UNSAFE_CANDIDATE = _UNSAFE_ELABORATION
UNSAFE_DECLARATION_RE = re.compile(
    r"(?m)^[ \t]*(?:@\[[^\]\r\n]*\][ \t]*)*"
    r"(?:(?:private|protected|noncomputable|local|scoped)[ \t]+)*unsafe\b",
    re.IGNORECASE,
)
INJECTED_COMMAND_RE = re.compile(
    r"(?m)^[ \t]*(?:import|namespace|section|end|open|attribute|set_option|theorem|lemma|def|abbrev|"
    r"instance|structure|class|inductive|coinductive|axiom|opaque|example|elab|macro|syntax|unsafe)\b"
)
FULL_DECLARATION_RE = re.compile(
    r"(?m)^(?P<indent>[ \t]*)(?:(?:private|protected|noncomputable|local|scoped)[ \t]+)*"
    r"(?P<kind>theorem|lemma|def|abbrev|instance|structure|class|inductive|coinductive|"
    r"axiom|opaque|example|namespace|section|end|variable|include|omit|open|attribute|"
    r"set_option)\b(?:[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_']*"
    r"(?:\.[A-Za-z_][A-Za-z0-9_']*)*))?",
    re.IGNORECASE,
)
LEAN_QUALIFIED_NAME_RE = re.compile(
    r"^(?:[^\W\d]|_)[\w']*(?:\.(?:[^\W\d]|_)[\w']*)*$",
    re.UNICODE,
)
_INCOMPLETE_PROOF_DIAGNOSTIC = re.compile(r"(?i)(?:uses?\s+['`]?sorry|\bsorryAx\b)")
_COMMAND_START = re.compile(
    r"(?m)^\s*(?:theorem|lemma|example|def|abbrev|opaque|axiom|structure|class|"
    r"inductive|instance|namespace|section|end|variable|open|local|attribute|"
    r"notation|infix|prefix|postfix)\b"
)


@dataclass
class CompileResult:
    ok: bool
    elapsed_ms: float
    diagnostics: str
    isolated_source: str
    timed_out: bool = False
    returncode: int | None = None
    compiler_command: list[str] | None = None


@dataclass
class FileCompileResult:
    """直接编译已有 Lean 文件的结果。"""

    ok: bool
    elapsed_ms: float
    diagnostics: str
    timed_out: bool = False
    returncode: int | None = None
    compiler_command: list[str] | None = None


CANDIDATE_POLICY = {
    "version": "tracer-candidate-v2",
    "meta_execution": "blocked",
    "unsafe_declarations": "blocked",
    "environment": "minimal",
}


def find_project_root(path: Path) -> Path | None:
    """寻找最近的 Lake 项目根目录。"""

    resolved = path.resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    for parent in (start, *start.parents):
        if (parent / "lakefile.toml").exists() or (parent / "lakefile.lean").exists():
            return parent
    return None


def lean_subprocess_environment(project_root: Path | None = None, scratch_home: Path | None = None) -> dict[str, str]:
    """构造最小化的 Lean 子进程环境，不继承密钥、令牌或代理凭据。"""

    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _SAFE_ENVIRONMENT_NAMES or name.upper() in {"LC_ALL", "LC_CTYPE", "LC_MESSAGES", "TERM", "NO_COLOR"}
    }
    if not environment.get("ELAN_HOME"):
        user_profile = environment.get("USERPROFILE")
        if user_profile and (Path(user_profile) / ".elan").exists():
            environment["ELAN_HOME"] = str(Path(user_profile) / ".elan")
    if scratch_home:
        scratch_home.mkdir(parents=True, exist_ok=True)
        temp_dir = scratch_home / "tmp"
        app_data = scratch_home / "appdata"
        local_app_data = scratch_home / "localappdata"
        for path in (temp_dir, app_data, local_app_data):
            path.mkdir(parents=True, exist_ok=True)
        environment.update(
            {
                "HOME": str(scratch_home),
                "USERPROFILE": str(scratch_home),
                "TMP": str(temp_dir),
                "TEMP": str(temp_dir),
                "TMPDIR": str(temp_dir),
                "APPDATA": str(app_data),
                "LOCALAPPDATA": str(local_app_data),
                "TRACER_CANDIDATE_ENV": "isolated",
            }
        )
    if project_root:
        environment["LEAN_PATH"] = str(project_root)
    environment["TRACER_LEAN_CHILD"] = "1"
    return environment


def validate_candidate_safety(candidate: str) -> None:
    """拒绝能显式触发本机元编程、IO 或进程执行的候选。"""

    violation = candidate_safety_violation(candidate)
    if violation:
        raise ValueError(violation)


def source_meta_execution_violation(source: str) -> bool:
    """识别源码中的编译期元编程入口或 unsafe 声明。"""

    cleaned = _strip_lean_comments(source)
    return bool(_UNSAFE_ELABORATION.search(cleaned) or UNSAFE_DECLARATION_RE.search(cleaned))


def candidate_safety_violation(candidate: str) -> str | None:
    """拒绝局部证明中的元编程入口、unsafe 声明或额外顶层命令。"""

    if source_meta_execution_violation(candidate):
        return "禁止的本机执行构造：候选包含不允许的 Lean 元编程、本机执行入口或 unsafe 声明"
    if any(INJECTED_COMMAND_RE.match(line) for line in candidate.splitlines()):
        return "候选试图注入额外 Lean 命令"
    return None


def _strip_lean_comments(source: str) -> str:
    """Remove nested Lean comments while preserving line boundaries."""

    output: list[str] = []
    index = 0
    block_depth = 0
    in_string = False
    escaped = False
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if block_depth:
            if current == "/" and following == "-":
                block_depth += 1
                output.extend("  ")
                index += 2
                continue
            if current == "-" and following == "/":
                block_depth -= 1
                output.extend("  ")
                index += 2
                continue
            output.append("\n" if current == "\n" else " ")
            index += 1
            continue
        if not in_string and current == "-" and following == "-":
            while index < len(source) and source[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if not in_string and current == "/" and following == "-":
            block_depth = 1
            output.extend("  ")
            index += 2
            continue
        output.append(current)
        if in_string:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                in_string = False
        elif current == '"':
            in_string = True
        index += 1
    return "".join(output)


def _declaration_header(source: str) -> str | None:
    """Return normalized declaration text before its top-level ``:=`` body."""

    cleaned = _strip_lean_comments(source)
    round_depth = square_depth = brace_depth = 0
    in_string = False
    escaped = False
    index = 0
    while index + 1 < len(cleaned):
        current = cleaned[index]
        if in_string:
            if escaped:
                escaped = False
            elif current == "\\":
                escaped = True
            elif current == '"':
                in_string = False
            index += 1
            continue
        if current == '"':
            in_string = True
        elif current == "(":
            round_depth += 1
        elif current == ")":
            round_depth = max(0, round_depth - 1)
        elif current == "[":
            square_depth += 1
        elif current == "]":
            square_depth = max(0, square_depth - 1)
        elif current == "{":
            brace_depth += 1
        elif current == "}":
            brace_depth = max(0, brace_depth - 1)
        elif (
            current == ":"
            and cleaned[index + 1] == "="
            and round_depth == square_depth == brace_depth == 0
        ):
            return re.sub(r"\s+", " ", cleaned[:index]).strip()
        index += 1
    return None


def full_theorem_safety_violation(
    candidate: str,
    *,
    expected_name: str,
    original_source: str,
    imports: list[str] | tuple[str, ...] = (),
    opens: list[str] | tuple[str, ...] = (),
) -> str | None:
    """Fail closed on unsafe or structurally changed full-theorem proposals."""

    if source_meta_execution_violation(candidate):
        return "完整 theorem 候选包含不允许的元编程、命令执行入口或 unsafe 声明"
    if PLACEHOLDER_RE.search(candidate):
        return "完整 theorem 候选包含 sorry、sorryAx 或 admit"
    for label, values in (("import", imports), ("open", opens)):
        if any(not LEAN_QUALIFIED_NAME_RE.fullmatch(str(value).strip()) for value in values):
            return f"完整 theorem 候选包含非法 {label} 名称"

    cleaned = _strip_lean_comments(candidate)
    declarations = list(FULL_DECLARATION_RE.finditer(cleaned))
    if not declarations:
        return "完整 theorem 候选缺少顶层声明"
    first = declarations[0]
    if cleaned[: first.start()].strip():
        return "完整 theorem 候选在目标声明前包含额外内容"
    base_indent = len(first.group("indent").expandtabs(8))
    top_level = [
        declaration
        for declaration in declarations
        if len(declaration.group("indent").expandtabs(8)) <= base_indent
    ]
    if len(top_level) != 1:
        return "完整 theorem 候选必须且只能包含一个顶层声明"
    if first.group("kind").lower() not in {"theorem", "lemma"}:
        return "完整 theorem 候选必须保持 theorem 或 lemma 声明"
    expected_full_name = str(expected_name)
    expected_short_name = expected_full_name.rsplit(".", 1)[-1]
    if first.group("name") not in {expected_full_name, expected_short_name}:
        return "完整 theorem 候选修改了目标声明名称"

    original_header = _declaration_header(original_source)
    candidate_header = _declaration_header(candidate)
    if not original_header or not candidate_header:
        return "无法确定完整 theorem 候选的声明头"
    if candidate_header != original_header:
        return "完整 theorem 候选修改了目标定理陈述"
    return None


def diagnostics_use_sorry(diagnostics: str) -> bool:
    """检测 Lean 对未完成证明公理的警告。"""

    return bool(SORRY_WARNING_RE.search(diagnostics) or _INCOMPLETE_PROOF_DIAGNOSTIC.search(diagnostics))


def _direct_lean_command(path: Path) -> list[str]:
    """为非 Lake 文件选择显式工具链，避免依赖机器的默认 Elan 配置。"""

    resolved = path.resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    candidates = [*(parent / "lean-toolchain" for parent in (start, *start.parents)), REPOSITORY_ROOT / "lean-toolchain"]
    toolchain_file = next((candidate for candidate in candidates if candidate.exists()), None)
    if toolchain_file is not None and shutil.which("elan"):
        toolchain = toolchain_file.read_text(encoding="utf-8").strip()
        if toolchain:
            return ["elan", "run", toolchain, "lean", str(path)]
    return ["lean", str(path)]


def lean_command(path: Path, project_root: Path | None = None) -> list[str]:
    root = project_root or find_project_root(path)
    # capsule 的 lakefile 只用于记录来源；没有本地构建目录时直接调用 Lean，
    # 避免 Lake 为不存在的项目目标反复解析配置或等待网络。
    if root and (root / "capsule.json").exists() and not (root / ".lake").exists():
        return _direct_lean_command(path)
    return ["lake", "env", "lean", str(path)] if root else _direct_lean_command(path)


def run_lean_file(path: Path, timeout: float = 20.0, project_root: Path | None = None) -> FileCompileResult:
    """优先在 Lake 环境中直接编译具体 Lean 文件。"""

    path = path.resolve()
    root = project_root.resolve() if project_root else find_project_root(path)
    command = lean_command(path, root)
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="tracer-lean-env-") as scratch:
            environment = lean_subprocess_environment(root, Path(scratch))
            process = subprocess.run(
                command,
                cwd=root or path.parent,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
                env=environment,
            )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        return FileCompileResult(False, elapsed_ms, f"Lean 编译超时（{timeout:g}s）\n{stdout}\n{stderr}".strip(), True, None, command)
    except FileNotFoundError as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        return FileCompileResult(False, elapsed_ms, f"编译器不可用: {exc}", False, None, command)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    diagnostics = "\n".join(part for part in [process.stdout, process.stderr] if part).strip()
    return FileCompileResult(process.returncode == 0, elapsed_ms, diagnostics, False, process.returncode, command)


def _open_blocks_before(source: str, position: int) -> list[tuple[str, str | None]]:
    blocks: list[tuple[str, str | None]] = []
    for line in source[:position].splitlines():
        namespace = re.match(r"^\s*namespace\s+([A-Za-z_][A-Za-z0-9_.']*)\s*$", line)
        section = re.match(r"^\s*section(?:\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$", line)
        closing = re.match(r"^\s*end(?:\s+[A-Za-z_][A-Za-z0-9_.]*)?\s*$", line)
        if namespace:
            blocks.append(("namespace", namespace.group(1)))
        elif section:
            blocks.append(("section", section.group(1)))
        elif closing and blocks:
            closing_name = re.match(r"^\s*end(?:\s+([A-Za-z_][A-Za-z0-9_.']*))?\s*$", line)
            if closing_name and closing_name.group(1):
                for index in range(len(blocks) - 1, -1, -1):
                    if blocks[index][1] and blocks[index][1].split(".")[-1] == closing_name.group(1).split(".")[-1]:
                        del blocks[index:]
                        break
            else:
                blocks.pop()
    return blocks


def _namespace_before(source: str, position: int) -> str | None:
    names = [name for kind, name in _open_blocks_before(source, position) if kind == "namespace" and name]
    parts: list[str] = []
    for name in names:
        if name.startswith("_root_."):
            parts = name.removeprefix("_root_").lstrip(".").split(".")
        else:
            parts.extend(name.split("."))
    return ".".join(parts) if parts else None


def declaration_scope(source: str, theorem_name: str) -> tuple[int, int]:
    short_name = theorem_name.rsplit(".", 1)[-1]
    matches = list(re.finditer(rf"(?m)^\s*(?:theorem|lemma)\s+{re.escape(short_name)}\b", source))
    requested_namespace = theorem_name.rsplit(".", 1)[0] if "." in theorem_name else None
    exact_matches = [
        candidate for candidate in matches
        if requested_namespace is None or _namespace_before(source, candidate.start()) == requested_namespace
    ]
    if not exact_matches:
        raise ValueError(f"找不到目标定理: {theorem_name}")
    if requested_namespace is None and len(exact_matches) != 1:
        raise ValueError(f"定理名不唯一，请使用完全限定名称: {theorem_name}")
    if len(exact_matches) != 1:
        raise ValueError(f"完全限定定理名不唯一: {theorem_name}")
    match = exact_matches[0]
    next_command = _COMMAND_START.search(source, match.end())
    return match.start(), next_command.start() if next_command else len(source)


_declaration_scope = declaration_scope


def patch_proof_region(source: str, candidate: str, theorem_name: str, start: str, end: str, placeholder: str = "sorry") -> str:
    scope_start, scope_end = declaration_scope(source, theorem_name)
    scope = source[scope_start:scope_end]
    if start in candidate or end in candidate:
        raise ValueError("候选证明不能包含证明区域标记")
    if scope.count(start) == 1 and scope.count(end) == 1:
        left = scope_start + scope.index(start) + len(start)
        right = scope_start + scope.index(end)
    else:
        placeholders = list(re.finditer(rf"(?<![A-Za-z0-9_]){re.escape(placeholder)}(?![A-Za-z0-9_])", scope))
        if len(placeholders) != 1:
            raise ValueError("目标定理必须包含唯一证明区域标记，或唯一占位符")
        left = scope_start + placeholders[0].start()
        right = scope_start + placeholders[0].end()
    if left > right:
        raise ValueError("证明区域标记顺序错误")
    return source[:left] + "\n  " + candidate.strip() + "\n  " + source[right:]


def isolate_target(source: str, patched: str, theorem_name: str) -> str:
    scope_start, scope_end = declaration_scope(patched, theorem_name)
    context = source[:scope_start]
    # 保留局部定义和已完成的前置声明，只移除含占位符的旧 theorem/lemma，
    # 以免同一评测文件中的其他未完成题污染目标证明。
    declaration_starts = list(re.finditer(r"(?m)^\s*(?:theorem|lemma)\s+", context))
    removals: list[tuple[int, int]] = []
    for declaration in declaration_starts:
        next_command = _COMMAND_START.search(context, declaration.end())
        end_position = next_command.start() if next_command else len(context)
        block = context[declaration.start():end_position]
        if re.search(r"\b(?:sorry|admit)\b|--\s*PROOF_START", block):
            removals.append((declaration.start(), end_position))
    for left, right in reversed(removals):
        context = context[:left] + context[right:]
    closings = []
    for kind, name in reversed(_open_blocks_before(source, scope_start)):
        closings.append(f"end {name}" if name else "end")
    return context.rstrip() + "\n\n" + patched[scope_start:scope_end].rstrip() + "\n\n" + "\n".join(closings) + "\n"


def compile_candidate(
    source_path: Path,
    source: str,
    candidate: str,
    theorem_name: str,
    start_marker: str = "-- PROOF_START",
    end_marker: str = "-- PROOF_END",
    timeout: float = 20.0,
    placeholder: str = "sorry",
) -> CompileResult:
    validate_candidate_safety(candidate)
    patched = patch_proof_region(source, candidate, theorem_name, start_marker, end_marker, placeholder)
    isolated = isolate_target(source, patched, theorem_name)
    with tempfile.TemporaryDirectory(prefix="lean-proof-repair-") as temp_dir:
        temp_path = Path(temp_dir) / source_path.name
        temp_path.write_text(isolated, encoding="utf-8")
        started = time.perf_counter()
        try:
            project_root = find_project_root(source_path)
            environment = lean_subprocess_environment(project_root, Path(temp_dir) / "home")
            command = ["lake", "env", "lean", "-DwarningAsError=true", str(temp_path)] if project_root else _direct_lean_command(temp_path)
            if not project_root:
                command.insert(-1, "-DwarningAsError=true")
            process = subprocess.run(
                command,
                cwd=project_root or source_path.parent,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            diagnostics = f"Lean 编译超时（{timeout:g}s）\n{stdout}\n{stderr}".strip()
            return CompileResult(False, elapsed_ms, diagnostics, isolated, True, None, command)
        except FileNotFoundError as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            return CompileResult(False, elapsed_ms, f"编译器不可用: {exc}", isolated, False, None, command)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    diagnostics = "\n".join(part for part in [process.stdout, process.stderr] if part).strip()
    incomplete = bool(_INCOMPLETE_PROOF_DIAGNOSTIC.search(diagnostics))
    if incomplete and "TRACER" not in diagnostics:
        diagnostics = (diagnostics + "\nTRACER: 目标证明依赖未完成证明公理。 ").strip()
    return CompileResult(process.returncode == 0 and not incomplete, elapsed_ms, diagnostics, isolated, False, process.returncode, command)
