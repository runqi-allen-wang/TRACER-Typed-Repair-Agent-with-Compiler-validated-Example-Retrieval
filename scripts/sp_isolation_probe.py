#!/usr/bin/env python3
"""在受限容器内部测量 SP 操作系统边界；不得在宿主机直接用作通过证据。"""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path


PROFILE_PATH = Path("/workspace/benchmarks/security/isolation_profile.json")


def _attempt_write(path: Path) -> tuple[bool, str]:
    """返回写入是否被拒绝，并尽量清理意外创建的探针文件。"""

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("TRACER SP isolation probe\n", encoding="utf-8")
    except OSError as exc:
        return True, f"{type(exc).__name__}:{exc.errno}"
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return False, "write_succeeded"


def _proc_status() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            values[name] = value.strip()
    return values


def _first_existing(paths: tuple[str, ...]) -> str | None:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    return None


def _integer_limit(value: str | None) -> int | None:
    if value is None or value == "max":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _cpu_limit() -> float | None:
    unified = _first_existing(("/sys/fs/cgroup/cpu.max",))
    if unified:
        fields = unified.split()
        if len(fields) == 2 and fields[0] != "max":
            try:
                return int(fields[0]) / int(fields[1])
            except (ValueError, ZeroDivisionError):
                return None
    quota = _integer_limit(_first_existing(("/sys/fs/cgroup/cpu/cpu.cfs_quota_us",)))
    period = _integer_limit(_first_existing(("/sys/fs/cgroup/cpu/cpu.cfs_period_us",)))
    if quota is None or period in (None, 0) or quota < 0:
        return None
    return quota / period


def _tmp_mount_options() -> set[str]:
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if separator and len(fields) >= 6 and fields[4] == "/tmp":
            options = set(fields[5].split(","))
            after_fields = after.split()
            if len(after_fields) >= 3:
                options.update(after_fields[2].split(","))
            return options
    return set()


def _network_egress_denied() -> tuple[bool, str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.5)
    try:
        result = sock.connect_ex(("1.1.1.1", 53))
    except OSError as exc:
        return True, f"{type(exc).__name__}:{exc.errno}"
    finally:
        sock.close()
    return result != 0, f"connect_ex:{result}"


def main() -> int:
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    limits = profile["limits"]
    status = _proc_status()
    rootfs_denied, rootfs_evidence = _attempt_write(Path("/tracer-sp-rootfs-probe"))
    workspace_denied, workspace_evidence = _attempt_write(Path("/workspace/.tracer-sp-write-probe"))
    tmp_denied, tmp_evidence = _attempt_write(Path("/tmp/tracer-sp/probe.txt"))
    network_denied, network_evidence = _network_egress_denied()
    memory_value = _integer_limit(_first_existing((
        "/sys/fs/cgroup/memory.max",
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",
    )))
    pids_value = _integer_limit(_first_existing((
        "/sys/fs/cgroup/pids.max",
        "/sys/fs/cgroup/pids/pids.max",
    )))
    cpu_value = _cpu_limit()
    mount_options = _tmp_mount_options()

    checks = {
        "non_root": os.geteuid() != 0,
        "read_only_rootfs": rootfs_denied,
        "read_only_workspace": workspace_denied,
        "network_egress_denied": network_denied,
        "effective_capabilities_zero": int(status.get("CapEff", "1"), 16) == 0,
        "no_new_privileges": status.get("NoNewPrivs") == "1",
        "seccomp_filter": status.get("Seccomp") == "2",
        "memory_limit": memory_value is not None and memory_value <= int(limits["memory_bytes"]),
        "pids_limit": pids_value is not None and pids_value <= int(limits["pids"]),
        "cpu_limit": cpu_value is not None and cpu_value <= float(limits["cpus"]) + 1e-9,
        "temporary_directory_writable": not tmp_denied,
        "temporary_directory_noexec": "noexec" in mount_options,
        "host_secret_not_inherited": "TRACER_SP_SECRET_CANARY" not in os.environ,
        "unmounted_host_sentinel_absent": not Path("/tracer-host-sentinel.txt").exists(),
    }
    evidence = {
        "effective_uid": os.geteuid(),
        "rootfs_write": rootfs_evidence,
        "workspace_write": workspace_evidence,
        "network": network_evidence,
        "temporary_write": tmp_evidence,
        "temporary_mount_options": sorted(mount_options),
        "effective_capabilities": status.get("CapEff"),
        "no_new_privileges": status.get("NoNewPrivs"),
        "seccomp": status.get("Seccomp"),
        "memory_limit_bytes": memory_value,
        "pids_limit": pids_value,
        "cpu_limit": cpu_value,
    }
    required = profile["required_controls"]
    result = {
        "profile_version": profile["version"],
        "checks": checks,
        "evidence": evidence,
        "all_required_controls_passed": all(checks.get(name) is True for name in required),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["all_required_controls_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
