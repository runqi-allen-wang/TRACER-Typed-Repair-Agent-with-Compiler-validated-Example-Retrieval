# TRACER-REAL 任务构建区

本目录只登记真实版本历史修复任务的构建协议，不把人工构造的 `repair24` 改名为真实数据。

候选任务必须满足：

1. 旧证明和修复证明来自同一公开 Git 仓库的两个明确版本；
2. 定理陈述在两个版本间保持不变；
3. 将旧证明放入修复版本的上下文后，Lean 能稳定复现非基础设施失败；
4. 修复证明在同一固定上下文和工具链中独立编译通过；
5. 公开任务目录不包含参考证明，参考证明写入独立的本地目录；
6. 来源、许可、版本、文件和定理名都进入可读 provenance 字段。

`seed_spec.example.json` 只是字段示例，不是已经验证的真实任务，也不进入样本计数。`mathlib_v1/`、`batteries_v1/` 和 `aesop_v1/` 分别由三个独立公开上游项目的真实历史构建；统一入口 [`tracer_real_v1/manifest.json`](tracer_real_v1/manifest.json) 冻结为 **11 题、3 项目**：

| 划分 | 上游项目 | 题数 | 用途 |
| --- | --- | ---: | --- |
| development | Mathlib | 3 | 构建器与长文件开发 |
| validation | Batteries | 4 | 协议和实现选择 |
| test | Aesop | 4 | 预注册后一次性项目外测试 |

同一上游 Git 项目不会跨划分。这里的 11 题仍是项目级**试点**，不是能够支持跨项目普适结论的大规模基准。

准备好已检出到修复版本的公开 Lean 仓库后运行：

```powershell
python src/real_repairs.py build `
  --repo C:\path\to\public-lean-repository `
  --spec benchmarks/real_repairs/seed_spec.local.json `
  --out results/tracer-real-seed `
  --reference-out private_references/tracer-real-seed
```

若来源仓库本身是另一个 Lake 项目的依赖，应显式指定已经冻结并构建的外层项目：

```powershell
python src/real_repairs.py build `
  --repo mathlib_project/.lake/packages/mathlib `
  --project-root mathlib_project `
  --spec benchmarks/real_repairs/mathlib_v1.spec.json `
  --out benchmarks/real_repairs/mathlib_v1 `
  --reference-out private_references/real_repairs_mathlib_v1
```

用因果 runner 读取该题库时同样传入 `--project-root mathlib_project`；计划预览不会访问网络：

```powershell
python src/causal_feedback.py plan `
  --config experiments/causal_feedback.tracer_real_v1.json `
  --benchmark benchmarks/real_repairs/tracer_real_v1/manifest.json `
  --project-root mathlib_project `
  --preregistration experiments/preregistrations/tracer_real_causal_v1.json
```

复现三个子集及统一清单时，先删除或改名自行生成的目标目录；构建器会拒绝覆盖：

```powershell
python src/real_repairs.py build --repo mathlib_project/.lake/packages/batteries --project-root mathlib_project --spec benchmarks/real_repairs/batteries_v1.spec.json --out results/rebuild/batteries_v1 --reference-out private_references/rebuild_batteries_v1 --timeout 180
python src/real_repairs.py build --repo mathlib_project/.lake/packages/aesop --project-root mathlib_project --spec benchmarks/real_repairs/aesop_v1.spec.json --out results/rebuild/aesop_v1 --reference-out private_references/rebuild_aesop_v1 --timeout 180
```

项目筛选还检查了 Plausible、Qq、ProofWidgets、ImportGraph、LeanSearchClient 与 Cli：没有通过全部门禁的候选不会为凑项目数进入清单。构建器不修改来源仓库，也不覆盖已有输出；参考证明仅写入 `.gitignore` 排除的 `private_references/`。
