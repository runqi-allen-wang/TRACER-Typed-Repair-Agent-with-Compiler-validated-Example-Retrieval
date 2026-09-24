"""审计公开的 TRACER SP 操作系统隔离证据包。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from security_isolation import check_report, load_profile  # noqa: E402


RELEASE_VERSION = "tracer-sp-isolation-release-v1"
DEFAULT_RELEASE = ROOT / "published" / "security-isolation-tracer-sp-v1"
LOCAL_PATH_PATTERNS = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/home/runner/", re.IGNORECASE),
    re.compile(r"/Users/", re.IGNORECASE),
)
SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?:api[_-]?key|authorization|password|bearer|https?_proxy|all_proxy)"
    r"\s*[:=]\s*[^\s,}\]]+"
)


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return value


def audit_release(release: Path, root: Path = ROOT) -> dict:
    release = release.resolve()
    errors: list[str] = []
    release_file = release / "release.json"
    report_file = release / "linux-github-actions" / "report.json"
    required_files = (
        release / "README.md",
        release_file,
        release / "linux-github-actions" / "README.md",
        report_file,
    )
    for path in required_files:
        if not path.is_file():
            errors.append(f"缺少发布文件: {path.relative_to(release)}")
    if errors:
        return {"ok": False, "errors": errors}

    metadata = _load_json(release_file)
    report = _load_json(report_file)
    profile = load_profile(root)
    observed = metadata.get("platforms", {}).get("linux_github_actions", {})
    pending = metadata.get("platforms", {}).get("windows_docker_desktop", {})

    if metadata.get("release_version") != RELEASE_VERSION:
        errors.append("发布版本不一致")
    if metadata.get("evidence_status") != "single_platform_observed":
        errors.append("发布状态必须明确为单平台已观察")
    if observed.get("status") != "observed_pass":
        errors.append("Linux 平台状态不是 observed_pass")
    if pending.get("status") != "pending" or pending.get("report") is not None:
        errors.append("Windows Docker Desktop 必须保持 pending 且没有伪造报告")
    if observed.get("report") != "linux-github-actions/report.json":
        errors.append("Linux 报告相对路径不一致")
    run_url = str(observed.get("workflow_run_url", ""))
    if not re.fullmatch(
        r"https://github\.com/runqi-allen-wang/"
        r"TRACER-Typed-Repair-Agent-with-Compiler-validated-Example-Retrieval/"
        r"actions/runs/[0-9]+",
        run_url,
    ):
        errors.append("GitHub Actions 运行地址无效")
    source_commit = str(observed.get("source_commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        errors.append("源提交标识无效")

    checked = check_report(root, report_file)
    errors.extend(checked["errors"])
    checks = report.get("probe", {}).get("checks", {})
    required_controls = profile["required_controls"]
    passed_controls = sum(checks.get(name) is True for name in required_controls)
    if set(checks) != set(required_controls):
        errors.append("报告控制集合与冻结配置不一致")
    if observed.get("required_controls") != len(required_controls):
        errors.append("发布元数据中的控制总数不一致")
    if observed.get("passed_controls") != passed_controls:
        errors.append("发布元数据中的通过控制数不一致")
    if report.get("host_os") != "Linux":
        errors.append("报告不是 Linux 宿主实测")
    if report.get("runtime", {}).get("kind") != "docker":
        errors.append("报告不是 Docker Engine 实测")
    if report.get("dangerous_lean_executed") is not False:
        errors.append("报告没有保持危险 Lean 夹具禁执行边界")

    for path in release.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if SECRET_ASSIGNMENT.search(text):
            errors.append(f"发布文件疑似包含凭据赋值: {path.relative_to(release)}")
        if any(pattern.search(text) for pattern in LOCAL_PATH_PATTERNS):
            errors.append(f"发布文件包含本机或 runner 绝对路径: {path.relative_to(release)}")

    return {
        "ok": not errors,
        "release_version": metadata.get("release_version"),
        "evidence_status": metadata.get("evidence_status"),
        "observed_platforms": 1,
        "pending_platforms": 1,
        "required_controls": len(required_controls),
        "passed_controls": passed_controls,
        "dangerous_lean_executed": report.get("dangerous_lean_executed"),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", nargs="?", type=Path, default=DEFAULT_RELEASE)
    args = parser.parse_args()
    try:
        result = audit_release(args.release)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        result = {"ok": False, "errors": [str(exc)]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
