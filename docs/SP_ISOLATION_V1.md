# SP 容器与低权限隔离协议 v1

`tracer-sp-isolation-v1` 是 SP-1～SP-12 文本门禁之后的操作系统边界原型。它不是新的 SP 编号，也不是 R-A～R-F 实验臂。其目的，是把“建议使用容器”变成可运行、可失败、可审计的边界探针。

## 冻结配置

机器可读配置位于 `benchmarks/security/isolation_profile.json`。运行器固定要求：

- Linux Docker 容器；
- 数字 UID/GID `65532:65532`，不得以 root 运行；
- 根文件系统与仓库挂载均只读；
- 只有独立的 `/tmp` tmpfs 可写，并启用 `noexec`、`nosuid`、`nodev`；
- 网络模式为 `none`；
- 删除全部 Linux capabilities，并启用 `no-new-privileges` 与默认 seccomp filter；
- 内存 512 MiB、CPU 1 核、PID 64、墙钟 90 秒；
- Docker 客户端使用最小环境，不携带模型 API key、token 或代理凭据。

容器探针逐项观察非 root 身份、根目录和仓库写入失败、网络连接失败、capabilities、`NoNewPrivs`、seccomp、cgroup 资源上限、`/tmp` 可写及 noexec，以及未显式传入的宿主 canary 不出现在容器中。任何必需字段缺失或为 false，整次运行都按 fail-closed 失败。

## 安全执行边界

本阶段不会直接执行 `benchmarks/security/` 下的 12 个危险 Lean 候选。容器内只执行 [受控 Python 探针](../scripts/sp_isolation_probe.py)，以无副作用操作测量语言无关的操作系统边界。这样可以验证容器配置，却不能证明 Lean 元编程、容器实现或未知攻击不存在逃逸。

本协议也不把镜像标签解释为不可变供应链证明。公开报告必须记录所用标签、本次是否下载镜像、Docker 客户端/服务端版本、宿主系统、每个控制的观察值及残余边界，但不得写入本机路径、API key 或完整宿主环境。

## 运行方式

离线查看计划，不要求 Docker：

```powershell
python src/security_isolation.py plan
```

本机已存在 `python:3.11-slim-bookworm` 时运行：

```powershell
$out = "results/sp-isolation-" + (Get-Date -Format "yyyyMMdd-HHmmss")
python src/security_isolation.py run --out $out
python src/security_isolation.py check "$out/report.json"
```

若本机尚无该镜像，并明确允许 Docker 联网下载：

```powershell
$out = "results/sp-isolation-" + (Get-Date -Format "yyyyMMdd-HHmmss")
python src/security_isolation.py run --allow-pull --out $out
python src/security_isolation.py check "$out/report.json"
```

GitHub Actions 中的 `.github/workflows/sp-isolation.yml` 仅支持手动触发，不在普通 push/PR 中自动下载镜像或制造“已运行”证据。首次实测已由该工作流在 GitHub-hosted Ubuntu runner 上完成，报告发布于 [`published/security-isolation-tracer-sp-v1/`](../published/security-isolation-tracer-sp-v1/)。普通 CI 只审计这份已提交证据，不重新运行 Docker。

## 当前状态与完成门槛

代码、冻结配置、静态回归和手动工作流已经实现。原生 Linux Docker Engine 的首次报告已观察到 14/14 项冻结控制，并通过发布审计；危险 Lean 夹具没有在容器中执行。该报告只构成单平台证据，不能写成“双平台操作系统隔离已完成”。完整阶段至少需要：

1. Windows Docker Desktop 的 Linux 容器运行报告；
2. 原生 Linux Docker Engine 的独立运行报告（已完成）；
3. 两份报告均通过 `check`，且全部 14 个控制为 true；
4. 脱敏检查确认没有凭据、用户名、本机绝对路径或宿主完整环境；
5. 两个平台差异被逐字段说明，而不是只给一个总 PASS。

即使上述条件全部满足，结论也只能是“冻结探针在两个环境观察到所声明边界”，不能表述为完整沙箱或任意 Lean 程序安全。

当前已发布报告可用以下命令独立检查：

```powershell
python src/security_isolation.py check published/security-isolation-tracer-sp-v1/linux-github-actions/report.json
python scripts/audit_security_isolation_release.py published/security-isolation-tracer-sp-v1
```
