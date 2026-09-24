# TRACER SP 操作系统隔离证据 v1

本发布包保存 `tracer-sp-isolation-v1` 的第一份真实运行证据。它位于 SP-1～SP-12 编译前文本策略之后，验证共用编译边界的容器控制；它不是新的 SP 编号，也不是证明修复实验臂。

This release preserves the first observed run of `tracer-sp-isolation-v1`. It evaluates the container boundary shared by SP-1 through SP-12 after the pre-compilation policy gate. It is neither a new SP identifier nor a proof-repair research arm.

## 已观察结果 / Observed result

| 环境 | 状态 | 控制 | 证据 |
| --- | --- | ---: | --- |
| GitHub-hosted Ubuntu Linux + Docker Engine | 通过 | 14/14 | [`linux-github-actions/report.json`](linux-github-actions/report.json) |
| Windows Docker Desktop（Linux 容器） | 待运行 | — | 尚无报告 |

Linux 运行在提交 `18b477673ace25906557045f919e128cf61e58a7` 上由手动 Actions 工作流产生：[查看运行 36004997480](https://github.com/runqi-allen-wang/TRACER-Typed-Repair-Agent-with-Compiler-validated-Example-Retrieval/actions/runs/36004997480)。报告观察到非 root、只读根和工作区、禁网、零 effective capabilities、`no-new-privileges`、seccomp、内存/CPU/PID 限制，以及可写但 noexec 的临时目录。危险 Lean 夹具未被执行。

The Linux run observed all 14 frozen controls. Dangerous Lean fixtures were not executed. Windows Docker Desktop remains pending, so this release is intentionally marked `single_platform_observed` rather than complete dual-platform evidence.

## 复验 / Audit

```powershell
python src/security_isolation.py check published/security-isolation-tracer-sp-v1/linux-github-actions/report.json
python scripts/audit_security_isolation_release.py published/security-isolation-tracer-sp-v1
```

这份证据不能证明完整沙箱、双平台一致、未知容器逃逸不存在、恶意依赖安全或任意 Lean 元程序安全。
