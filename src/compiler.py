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
UNSAFE_ELABORATION_RE = re.compile(
    r"(?<![A-Za-z0-9_'])(?:run_tac|run_term_elab|eval_tac|elab_rules|macro_rules)(?![A-Za-z0-9_'])"
    r"|#[A-Za-z_][A-Za-z0-9_']*",
    re.IGNORECASE,
)
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
    r"set_option)\b(?:[ \t]+(?P<name>[A-Za-z_][A-Za-z0-9_']*))?",
    re.IGNORECASE,
)
LEAN_QUALIFIED_NAME_RE = re.compile(
    r"^(?:[^\W\d]|_)[\w']*(?:\.(?:[^\W\d]|_)[\w']*)*$",
    re.UNICODE,
)
LEAN_ENV_PASSTHROUGH = {
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
    "ELAN_HOME", "LEAN_PATH", "LEAN_SYSROOT", "LAKE_HOME",
    "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
    "LANG", "LC_ALL", "LC_CTYPE", "TERM", "NO_COLOR",
}
CANDIDATE_POLICY = {
    "version": "tracer-candidate-v2",
    "meta_execution": "blocked",
    "unsafe_declarations": "blocked",
    "environment": "minimal",
}


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


def candidate_safety_violation(candidate: str) -> str | None:
    """拒绝模型候选中的元编程执行入口和额外顶层命令。"""

    if source_meta_execution_violation(candidate):
        return "候选包含不允许的 Lean 元编程、命令执行入口或 unsafe 声明"
    lines = candidate.splitlines()
    if any(INJECTED_COMMAND_RE.match(line) for line in lines):
        return "候选试图在局部证明后注入额外 Lean 命令"
    return None


def source_meta_execution_violation(source: str) -> bool:
    """识别公开回放工件中不允许的编译期执行入口或 unsafe 声明。"""

    cleaned = _strip_lean_comments(source)
    return bool(UNSAFE_ELABORATION_RE.search(cleaned) or UNSAFE_DECLARATION_RE.search(cleaned))


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
    """Return the normalized declaration text before its top-level ``:=`` body."""

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
    expected_short_name = str(expected_name).rsplit(".", 1)[-1]
    if first.group("name") != expected_short_name:
        return "完整 theorem 候选修改了目标声明名称"

    original_header = _declaration_header(original_source)
    candidate_header = _declaration_header(candidate)
    if not original_header or not candidate_header:
        return "无法确定完整 theorem 候选的声明头"
    if candidate_header != original_header:
        return "完整 theorem 候选修改了目标定理陈述"
    return None


def lean_subprocess_environment(scratch_home: Path, project_root: Path | None = None) -> dict[str, str]:
    """构造最小 Lean 环境，不把 API key、token 或其他父进程变量交给候选。"""

    source = os.environ
    environment = {
        name: source[name]
        for name in LEAN_ENV_PASSTHROUGH
        if source.get(name)
    }
    try:
        git_config_count = int(source.get("GIT_CONFIG_COUNT", "0"))
    except ValueError:
        git_config_count = 0
    safe_git_entries: list[tuple[str, str]] = []
    for index in range(max(0, git_config_count)):
        key = source.get(f"GIT_CONFIG_KEY_{index}", "")
        value = source.get(f"GIT_CONFIG_VALUE_{index}", "")
        if key.casefold() == "safe.directory" and value:
            safe_git_entries.append((key, value))
    if safe_git_entries:
        environment["GIT_CONFIG_COUNT"] = str(len(safe_git_entries))
        for index, (key, value) in enumerate(safe_git_entries):
            environment[f"GIT_CONFIG_KEY_{index}"] = key
            environment[f"GIT_CONFIG_VALUE_{index}"] = value
    if not environment.get("ELAN_HOME"):
        profile = source.get("USERPROFILE") or source.get("HOME")
        if profile and (Path(profile) / ".elan").exists():
            environment["ELAN_HOME"] = str(Path(profile) / ".elan")

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
        existing_lean_path = environment.get("LEAN_PATH", "")
        environment["LEAN_PATH"] = os.pathsep.join(
            part for part in (str(project_root), existing_lean_path) if part
        )
    return environment


def find_project_root(path: Path) -> Path | None:
    """寻找最近的 Lake 项目根目录。"""

    resolved = path.resolve()
    start = resolved if resolved.is_dir() else resolved.parent
    for parent in (start, *start.parents):
        if (parent / "lakefile.toml").exists() or (parent / "lakefile.lean").exists():
            return parent
    return None


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
            environment = lean_subprocess_environment(Path(scratch), root)
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


def _active_scopes(source: str, position: int) -> list[tuple[str, str | None]]:
    """Track the namespace/section stack up to a source position."""

    scopes: list[tuple[str, str | None]] = []
    for match in SCOPE_RE.finditer(source, 0, position):
        kind = match.group("kind")
        name = match.group("name")
        if kind == "end":
            if scopes:
                scopes.pop()
        elif kind == "namespace" and name:
            scopes.append((kind, name))
        elif kind == "section":
            scopes.append((kind, name))
    return scopes


def _namespace_before(source: str, position: int) -> str | None:
    parts: list[str] = []
    for kind, name in _active_scopes(source, position):
        if kind != "namespace" or not name:
            continue
        if name.startswith("_root_."):
            parts = name.removeprefix("_root_.").split(".")
        else:
            parts.extend(name.split("."))
    return ".".join(parts) or None


def _declaration_end(source: str, match: re.Match[str]) -> int:
    declaration_indent = len(match.group("indent").expandtabs(4))
    for command in COMMAND_RE.finditer(source, match.end()):
        command_indent = len(command.group("indent").expandtabs(4))
        if command_indent <= declaration_indent:
            return command.start()
    return len(source)


def declaration_scope(source: str, theorem_name: str) -> tuple[int, int]:
    short_name = theorem_name.rsplit(".", 1)[-1]
    matches = [match for match in DECLARATION_RE.finditer(source) if match.group("name") == short_name]
    requested_namespace = theorem_name.rsplit(".", 1)[0] if "." in theorem_name else None
    if requested_namespace is None:
        if len(matches) > 1:
            namespaces = sorted({_namespace_before(source, candidate.start()) or "_root_" for candidate in matches})
            raise ValueError(f"目标定理名不唯一: {theorem_name}；请使用限定名（候选命名空间: {', '.join(namespaces)}）")
        match = matches[0] if matches else None
    else:
        qualified = [
            candidate
            for candidate in matches
            if _namespace_before(source, candidate.start()) == requested_namespace
        ]
        match = qualified[0] if len(qualified) == 1 else None
    if match is None:
        raise ValueError(f"找不到目标定理: {theorem_name}")
    return match.start(), _declaration_end(source, match)


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
    candidate_block = "\n".join(f"  {line}" for line in candidate.strip().splitlines())
    return source[:left] + "\n" + candidate_block + "\n  " + source[right:]


def _strip_incomplete_declarations(source: str) -> str:
    """Drop earlier unfinished lemmas while retaining valid local helpers and context."""

    spans: list[tuple[int, int]] = []
    for match in DECLARATION_RE.finditer(source):
        end = _declaration_end(source, match)
        if PLACEHOLDER_RE.search(source[match.start():end]):
            spans.append((match.start(), end))
    if not spans:
        return source
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        if start < cursor:
            continue
        parts.append(source[cursor:start])
        cursor = end
    parts.append(source[cursor:])
    return "".join(parts)


def isolate_target(source: str, patched: str, theorem_name: str) -> str:
    scope_start, scope_end = declaration_scope(patched, theorem_name)
    prefix = _strip_incomplete_declarations(source[:scope_start]).rstrip()
    closers: list[str] = []
    for kind, name in reversed(_active_scopes(source, scope_start)):
        if name:
            closers.append(f"end {name.split('.')[-1]}")
        else:
            closers.append("end")
    parts = [part for part in (prefix, patched[scope_start:scope_end].strip(), "\n".join(closers)) if part]
    return "\n\n".join(parts) + "\n"


def diagnostics_use_sorry(diagnostics: str) -> bool:
    return bool(SORRY_WARNING_RE.search(diagnostics))


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
    violation = candidate_safety_violation(candidate)
    if violation:
        raise ValueError(violation)
    patched = patch_proof_region(source, candidate, theorem_name, start_marker, end_marker, placeholder)
    isolated = isolate_target(source, patched, theorem_name)
    with tempfile.TemporaryDirectory(prefix="lean-proof-repair-") as temp_dir:
        temp_path = Path(temp_dir) / source_path.name
        temp_path.write_text(isolated, encoding="utf-8")
        started = time.perf_counter()
        try:
            project_root = find_project_root(source_path)
            command = ["lake", "env", "lean", str(temp_path)] if project_root else _direct_lean_command(temp_path)
            environment = lean_subprocess_environment(Path(temp_dir) / "home", project_root)
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
    return CompileResult(process.returncode == 0, elapsed_ms, diagnostics, isolated, False, process.returncode, command)
