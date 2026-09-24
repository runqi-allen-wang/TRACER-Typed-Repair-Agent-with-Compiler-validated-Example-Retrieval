# TRACER SP v2 冻结安全回归

本目录发布 `tracer-sp-v2` 的确定性离线结果。SP 是 Security Policy 编号，不是 R-A～R-F 的研究实验臂。

## 结果

| 指标 | 观察值 |
| --- | ---: |
| 冻结危险候选 | 12 |
| 编译前误放行 | 0/12 |
| 冻结正常对照 | 8 |
| 策略误拒绝 | 0/8 |
| 正常对照 Lean 编译失败 | 0/8 |
| 危险候选在拒绝前启动编译 | 0/12 |
| 实际检测器与预期不一致 | 0/12 |

误放行率与误拒绝率的观察值均为 0，但 Wilson 95% 区间上界分别约为 24.3% 和 32.4%。因此本结果不能解释为零风险。

12 个危险候选覆盖 unsafe 声明，环境、进程、文件与网络访问，资源选项修改，import、axiom、`#eval` 和宏命令注入，以及 kernel-only 策略下的原生执行入口。危险候选只验证文本策略在 Lean 编译前拒绝，不会为实验目的在主机执行。8 个正常对照覆盖普通证明、构造式证明、注释、嵌套注释、字符串、标识符子串和无害的证明内 scoped option；全部由 Lean 真编译。

## 复验

在仓库根目录运行：

```powershell
python src/security_study.py --check published/security-study-tracer-sp-v2/report.json
python -m unittest tests.test_security_cases tests.test_security -v
```

第一条命令会重新读取冻结威胁模型、重新执行策略判断、真实编译 8 个正常对照，并与 [report.json](report.json) 逐字段核对。它不会调用模型 API，也不会执行 12 个危险候选。

## 证据边界

本目录证明当前文本门禁对这 12 个已知输入的行为，以及 8 个正常对照在当前 Lean 工具链下的可用性。它不是操作系统沙箱，也不证明未知元编程别名、恶意依赖初始化或任意 Lean 程序安全。后续的[单平台 Linux 隔离证据](../security-isolation-tracer-sp-v1/)已观察到 14/14 项冻结容器控制；Windows Docker Desktop 仍待实测，因此两份发布包都不能解释为完整沙箱或零风险保证。
