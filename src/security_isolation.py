"""规划、运行并核对 TRACER SP 的容器低权限隔离探针。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


PROTOCOL_VERSION = "tracer-sp-isolation-evaluation-v1"
PROFILE_RELATIVE_PATH = Path("benchmarks/security/isolation_profile.json")
_RUNTIME_ENVIRONMENT_NAMES = {
    "COMSPEC",
    "DOCKER_CONFIG",
    "DOCKER_CONTEXT",
    "DOCKER_HOST",
    "HOME",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
    "XDG_RUNTIME_DIR",
}


class IsolationError(RuntimeError):
    """表示容器运行时、配置或证据不满足冻结协议。"""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_profile(root: Path) -> dict:
    profile = json.loads((root / PROFILE_RELATIVE_PATH).read_text(encoding="utf-8"))
    required = profile.get("required_controls")
    if profile.get("version") != "tracer-sp-isolation-v1":
        raise IsolationError("未知的 SP 隔离配置版本")
    if not isinstance(required, list) or not required or len(required) != len(set(required)):
        raise IsolationError("SP 隔离配置中的 required_controls 无效")
    if profile.get("dangerous_lean_execution") != "forbidden":
        raise IsolationError("SP 隔离原型不得执行危险 Lean 夹具")
    return profile


def runtime_environment() -> dict[str, str]:
    """只向 Docker 客户端保留启动所需环境，不携带模型密钥或代理凭据。"""

    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _RUNTIME_ENVIRONMENT_NAMES
    }
    # 该固定值不是凭据，仅用于证明 Docker 不会把客户端任意环境自动注入容器。
    environment["TRACER_SP_SECRET_CANARY"] = "TRACER_SP_CANARY_NOT_A_SECRET"
    return environment


def build_container_command(root: Path, docker: str, image: str, profile: dict) -> list[str]:
    """构造不经过 shell 的冻结 Docker 命令。"""

    limits = profile["limits"]
    mount = f"type=bind,src={root.resolve()},dst=/workspace,readonly"
    tmpfs = "rw,noexec,nosuid,nodev," f"size={int(limits['tmpfs_bytes'])}"
    return [
        docker,
        "run",
        "--rm",
        "--read-only",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        str(int(limits["pids"])),
        "--memory",
        str(int(limits["memory_bytes"])),
        "--cpus",
        str(float(limits["cpus"])),
        "--user",
        profile["container_user"],
        "--tmpfs",
        f"/tmp:{tmpfs}",
        "--mount",
        mount,
        "--workdir",
        "/workspace",
        "--env",
        "HOME=/tmp/tracer-home",
        "--env",
        "PYTHONDONTWRITEBYTECODE=1",
        "--entrypoint",
        "python",
        image,
        "/workspace/scripts/sp_isolation_probe.py",
    ]


def plan(root: Path) -> dict:
    profile = load_profile(root)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "profile_version": profile["version"],
        "runtime": profile["runtime"],
        "image": profile["image"],
        "container_user": profile["container_user"],
        "limits": profile["limits"],
        "required_controls": profile["required_controls"],
        "dangerous_lean_execution": profile["dangerous_lean_execution"],
        "network_calls": 0,
        "status": "plan_only",
        "claim_boundary": profile["claim_boundary"],
    }


def _completed(
    args: list[str], environment: dict[str, str], timeout: float
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        timeout=timeout,
        check=False,
    )


def _runtime_details(docker: str, environment: dict[str, str]) -> dict[str, str]:
    version = _completed(
        [docker, "version", "--format", "{{.Client.Version}}|{{.Server.Version}}"],
        environment,
        20,
    )
    if version.returncode != 0:
        raise IsolationError("Docker 客户端无法连接 Linux 容器服务")
    info = _completed([docker, "info", "--format", "{{.OSType}}"], environment, 20)
    if info.returncode != 0 or info.stdout.strip().lower() != "linux":
        raise IsolationError("SP 隔离实验只接受 Linux 容器模式")
    client, separator, server = version.stdout.strip().partition("|")
    if not separator or not client or not server:
        raise IsolationError("无法读取 Docker 客户端与服务端版本")
    return {
        "kind": "docker",
        "client_version": client,
        "server_version": server,
        "os_type": "linux",
    }


def _ensure_image(
    docker: str, image: str, environment: dict[str, str], allow_pull: bool
) -> bool:
    inspected = _completed([docker, "image", "inspect", image], environment, 20)
    if inspected.returncode == 0:
        return False
    if not allow_pull:
        raise IsolationError("冻结容器镜像在本机不可用；如允许联网下载，请显式传入 --allow-pull")
    pulled = _completed([docker, "pull", image], environment, 300)
    if pulled.returncode != 0:
        raise IsolationError("冻结容器镜像下载失败")
    return True


def validate_probe(profile: dict, probe: dict) -> list[str]:
    errors: list[str] = []
    if probe.get("profile_version") != profile["version"]:
        errors.append("探针配置版本不一致")
    checks = probe.get("checks")
    if not isinstance(checks, dict):
        return errors + ["探针缺少 checks"]
    for name in profile["required_controls"]:
        if checks.get(name) is not True:
            errors.append(f"隔离控制未通过: {name}")
    if probe.get("all_required_controls_passed") is not True:
        errors.append("探针未确认全部冻结控制")
    return errors


def run_probe(root: Path, output: Path, allow_pull: bool) -> dict:
    profile = load_profile(root)
    selected_image = profile["image"]
    docker = shutil.which("docker")
    if not docker:
        raise IsolationError("未找到 Docker；当前只能运行 plan，不能生成真实隔离结果")
    environment = runtime_environment()
    runtime = _runtime_details(docker, environment)
    image_pulled = _ensure_image(docker, selected_image, environment, allow_pull)
    command = build_container_command(root, docker, selected_image, profile)
    try:
        completed = _completed(
            command,
            environment,
            float(profile["limits"]["wall_timeout_seconds"]),
        )
    except subprocess.TimeoutExpired as exc:
        raise IsolationError("SP 隔离探针超时并已由 Docker 客户端终止") from exc
    try:
        probe = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise IsolationError("容器没有返回有效的单条 JSON 探针结果") from exc
    errors = validate_probe(profile, probe)
    if completed.returncode != 0 and not errors:
        errors.append(f"容器探针退出码异常: {completed.returncode}")
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "profile_version": profile["version"],
        "recorded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "host_os": platform.system(),
        "runtime": runtime,
        "image": selected_image,
        "image_identity": "tag_only",
        "image_pulled_during_run": image_pulled,
        "dangerous_lean_executed": False,
        "configuration": {
            "container_user": profile["container_user"],
            "read_only_rootfs": True,
            "read_only_workspace": True,
            "network": "none",
            "capabilities": "none",
            "no_new_privileges": True,
            "limits": profile["limits"],
        },
        "probe": probe,
        "errors": errors,
        "ok": not errors,
        "claim_boundary": profile["claim_boundary"],
    }
    output.mkdir(parents=True, exist_ok=False)
    report_path = output / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(
        "# TRACER SP 隔离探针结果\n\n"
        f"- 协议：`{PROTOCOL_VERSION}`\n"
        f"- 配置：`{profile['version']}`\n"
        f"- 宿主系统：`{report['host_os']}`\n"
        f"- Docker：客户端 `{runtime['client_version']}`，服务端 `{runtime['server_version']}`\n"
        f"- 镜像标签：`{selected_image}`\n"
        f"- 冻结控制全部通过：`{str(report['ok']).lower()}`\n"
        "- 危险 Lean 夹具被执行：`false`\n\n"
        "该结果只证明本次运行中冻结探针观察到的容器边界，不代表完整沙箱。\n",
        encoding="utf-8",
    )
    return report


def check_report(root: Path, report_path: Path) -> dict:
    profile = load_profile(root)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if report.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("报告协议版本不一致")
    if report.get("profile_version") != profile["version"]:
        errors.append("报告配置版本不一致")
    if report.get("dangerous_lean_executed") is not False:
        errors.append("报告没有确认危险 Lean 夹具未执行")
    errors.extend(validate_probe(profile, report.get("probe", {})))
    if report.get("errors"):
        errors.append("原报告包含运行错误")
    if report.get("ok") is not True:
        errors.append("原报告未通过")
    return {"ok": not errors, "errors": errors, "report": str(report_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repository_root())
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("plan", help="离线显示冻结隔离配置，不访问容器或网络")
    run_parser = subparsers.add_parser("run", help="使用本机 Docker 执行低权限隔离探针")
    run_parser.add_argument("--out", type=Path, required=True)
    run_parser.add_argument(
        "--allow-pull", action="store_true", help="本机缺少镜像时允许 Docker 下载"
    )
    check_parser = subparsers.add_parser("check", help="离线核对已经生成的隔离报告")
    check_parser.add_argument("report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "plan":
            result = plan(root)
        elif args.command == "run":
            result = run_probe(root, args.out.resolve(), args.allow_pull)
        else:
            result = check_report(root, args.report.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 1
    except (IsolationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
