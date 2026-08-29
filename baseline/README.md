# Part 1：AxProverBase Experience baseline

本目录实现《一些细化idea.md》的 Part 1：在固定题集、固定 AxProverBase、固定
Lean/Mathlib、固定模型与预算下运行原始 Experience memory baseline，并生成可供
Part 2 复用首轮候选和执行严格配对检查的 JSONL。

## 冻结条件

| 项 | 固定值 |
|---|---|
| 题集 | FATE-M 前 25 题（15 core、10 challenge），见 `manifest.json` |
| FATE-M | tag `v4.28.0`，commit `4eb33c8ccd0ff058b461cd763cc406509129743f` |
| Lean / Mathlib | FATE-M `v4.28.0` 自带环境 |
| AxProverBase | commit `06dfadc9ab439755af5efcfe0add95bfef2733c7` |
| 模型 | `openai:gpt-5.6-sol` @ `https://yxai.chat/v1` |
| API | Responses，`store=false`，`reasoning.effort=high` |
| Memory | `ExperienceProcessor` |
| 轮数 | `max_iterations=4` |
| 工具 | Lean Search / Web Search 均关闭 |
| 最终 summary | 关闭 |

实际 Ax 配置由 `configs/axprover_part1_experience.yaml` 导入
`configs/axprover_yxai_gpt56_sol.yaml`。`baseline/config.yaml` 保存同一实验条件的
人类可读清单；`baseline/config_check.py` 会同时校验两者，防止漂移。

## 为什么真实运行不用 `run_baseline.py`

固定版本 Ax 的 CLI `-o` 只写出 `success/error/summary`，不包含首轮 Proposal、逐轮
metrics 或 token usage。直接解析该 JSON 会丢失 Part 2 配对所需信息。

- `run_baseline.py`：只用于无 API 的 mock 流程自测；真实模式会 fail closed。
- `run_api.py`：通过 Ax Python API 运行单题并读取 `ProverAgentState`。
- `run_batch.py`：逐题调用 `run_api.py`，任一题异常时返回非零退出码。

真实 runner 还会在 Ax Builder 前执行仓库的 `tracer-candidate-v2` 安全门禁，拒绝
`unsafe` 声明、占位证明、额外声明和元编程执行入口；SP-1 安全策略候选不会进入 Lean。

## 本地运行

1. 安装固定依赖：

```powershell
python -m pip install -r .\requirements-axprover-part2.txt
```

2. 获取固定题集并构建：

```powershell
git clone --depth 1 --branch v4.28.0 https://github.com/frenzymath/FATE-M.git .\FATE-M
git -C .\FATE-M rev-parse HEAD
Set-Location .\FATE-M
lake build
Set-Location ..
```

`rev-parse` 应输出 `4eb33c8ccd0ff058b461cd763cc406509129743f`。如果不一致，
不要把该次运行用于正式比较。

3. 在当前 PowerShell 会话安全设置 yxai key：

```powershell
$secureKey = Read-Host "请输入 API Key（输入不会显示）" -AsSecureString
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", $secureKey).Password
```

4. 先跑 3 道 core smoke：

```powershell
try {
    python .\baseline\run_batch.py `
        .\baseline\manifest.json `
        .\FATE-M `
        .\configs\axprover_part1_experience.yaml `
        .\runs\baseline.jsonl `
        3 core
}
finally {
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
    Remove-Variable secureKey -ErrorAction SilentlyContinue
}
```

完整 core 可把 `3` 改为 `15`；challenge 使用最后一个参数 `challenge`，数量为 `10`。
为避免重复行，每次正式运行应使用新的输出文件。

## 输出与 Part 2 连接

`runs/baseline.jsonl` 每题包含：

- 完整首轮 Proposal：theorem code、reasoning、imports、opens；空 reasoning 也是冻结输入的一部分，不能用说明文字替换；
- proposer / memory / reviewer / compiler 调用数；
- token、总运行时间、Builder 时间、成功轮次和 Ax metrics；
- 模型、endpoint、Responses、存储、推理强度、预算和 Ax commit；
- `tracer-candidate-v2` 安全策略；
- provider 未返回价格且未配置正式单价时，成本保持 `null`。

生成 Part 2 首轮缓存：

```powershell
python .\scripts\prepare_part2_first_round_cache.py `
    --baseline .\runs\baseline.jsonl `
    --out .\results\part2-first-round.json
```

两组真实结果完成后，必须运行 `scripts/validate_part2_pairing.py`。门禁会核对题目身份、
固定 Ax commit、完整首轮 Proposal、provider、预算、memory 条件和零额外调用声明；失败的
数据不能进入 Part 3 结论。

## CI

- `.github/workflows/part1.yml`：Ubuntu-only，无 API 的配置、mock 与固定 Ax smoke。
- `.github/workflows/part1_run.yml`：手动触发，固定 FATE-M commit，运行 3 道 core 真实 smoke，
  上传 `runs/baseline.jsonl`。需要仓库 Actions secret `OPENAI_API_KEY`。

不要提交 `.env.secrets`、`auth.json`、API key、真实运行缓存或原始 provider 响应。
