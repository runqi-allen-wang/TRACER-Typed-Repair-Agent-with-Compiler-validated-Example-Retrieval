# ACL 2027 因果反馈实验执行手册

本手册只描述新的 ACL 2027 嵌套实验。历史 `repair24` 和既有 TRACER-REAL v2 配置不改写，也不作为新实验结果。

## 冻结设计

- 题库：TRACER-REAL v2 测试划分，5 个完全独立的上游项目，254 道真实历史修复任务。
- 重复：每模型、每题 3 次。
- 确认性三臂：`content_free_retry`、`true_structured`、`counterfactual`。
- 扩展八臂：上述三臂加 raw、normalized、irrelevant、retrieval-only 和 adaptive。
- 嵌套原则：DeepSeek 与 GLM 跑八臂，其中的三臂直接进入跨模型主分析；MiniMax 只跑三臂。不重复生成已在八臂中存在的确认性分支。
- 主对比：同模型、同题、同重复、同一冻结首轮失败上的 `true_structured - content_free_retry`。

科学协议与两个运行时预注册位于：

- `experiments/preregistrations/tracer_acl2027_protocol_v1.json`
- `experiments/preregistrations/tracer_acl2027_extended_v1.json`
- `experiments/preregistrations/tracer_acl2027_minimax_confirmatory_v1.json`

## 执行顺序

### 1. 离线审计

```powershell
python src/acl2027.py audit
```

只有在输出中同时出现 `ok: true`、`retrieval_declaration_leaks: 0` 和 `ready_for_benchmark_run: true` 时才可继续。该命令网络调用数为 0。

### 2. 三个一方 provider 的合成定理预检

```powershell
.\scripts\preflight_acl2027.ps1
```

脚本会依次隐藏读取 DeepSeek、智谱 BigModel 和 MiniMax 密钥；密钥只存在于当前进程环境，结束时删除。预检只发送合成的 `True` 定理，不读取也不发送 TRACER-REAL。

若只有 MiniMax 认证失败，不要重复请求已经通过的 DeepSeek/GLM；更换或核对 MiniMax 一方平台密钥后单独运行：

```powershell
.\scripts\preflight_acl2027.ps1 -Provider MiniMax
```

### 3. 付费实验

付费运行只能在三个预检均通过后开始。DeepSeek/GLM 扩展批次的最坏上限为 13,716 次 provider 调用，MiniMax 确认批次为 3,048 次；实际分支数由合格首轮失败数决定。不得为追求全通过删除失败记录或换模型重开。

冻结端点与模型分别为 DeepSeek `deepseek-v4-pro`、智谱 BigModel `glm-4.5` 和 MiniMax 中国区 `MiniMax-M3`。三者均通过各自一方域名调用；GLM 与 MiniMax 使用其官方 OpenAI-compatible Chat Completions 接口。MiniMax 密钥来自 `platform.minimax.cn`，因此端点冻结为 `https://api.minimax.cn/v1/chat/completions`，并设置 `reasoning_split=true`，使思考内容与送入 Lean 的最终候选分离。GLM 与 MiniMax 中国区价格未在本次冻结中录入，相关成本必须报告为未知而不是 0。

正式运行统一通过 `scripts/run_acl2027_formal.ps1`。脚本为每次实验创建独立会话根目录，并把扩展批次与 MiniMax 确认批次分别写入 `extended/` 和 `minimax-confirmatory/`；密钥只在当前 PowerShell 进程中存在。

首次运行必须明确给出两个批次的预算上限，或显式确认不设置脚本级费用上限：

```powershell
.\scripts\run_acl2027_formal.ps1 `
  -Batch All `
  -ExtendedBudgetUsd 100 `
  -MiniMaxBudgetUsd 30
```

如果使用 `-NoCostLimit`，其含义只是关闭 TRACER 的本地保守预留门禁，并不代表供应商账户没有计费或硬限额。正式大批次不应只为追求全通过而重开。

脚本启动后会打印唯一 `RunRoot`。若终端、网络或机器中断，必须使用同一个根目录续跑：

```powershell
.\scripts\run_acl2027_formal.ps1 `
  -Batch All `
  -RunRoot "results/acl2027-formal-YYYYMMDD-HHMMSS-xxxxxxxx" `
  -Resume `
  -ExtendedBudgetUsd 100 `
  -MiniMaxBudgetUsd 30
```

续跑会先校验会话合同、冻结计划、题库、提示模板、编译环境和预算账本。已完成且审计通过的批次直接跳过；未完成请求只从尚未落盘的任务继续。每次尝试的控制台日志写入 `_runner/attempts/`，非零退出同时产生失败记录；脚本从不删除失败轨迹或已有证明。`-SkipPreflight` 只应用于操作者明确决定跳过本次合成连接检查的情形，不改变正式实验的预注册内容。

### 4. 运行后门禁

每个批次必须依次完成：严格续跑核对、轨迹审计、所有成功证明独立复编译、AI 辅助盲审、项目等权配对分析、脱敏发布审计和论文图表生成。在三模型完整通过前，不宣称跨模型因果增益。

## 当前状态

离线预注册、五项目/254 题门禁、六类错误覆盖、检索声明重合审计和可续跑正式入口已实现。三家 provider 的合成 `True` 定理预检已在操作者会话中通过，但仓库尚未保存正式付费批次，因此仍不得表述为 TRACER-REAL 模型结果。
