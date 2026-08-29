# 贡献指南

1. 安装 Python 3.10+，并使用 `lean-toolchain` 指定的 Lean/Lake 版本。
2. 提交前运行 `python -m unittest discover -s tests -v`。
3. 修改 Lean 编译链路后运行 `lake build`。
4. 修改公开案例后运行 `python -m leancapsule audit capsules` 和 `python -m leancapsule verify capsules`。
5. 不得在正式评测路径中加入标准答案表或按题号路由的确定性答案逻辑。
6. provider 凭据只通过进程内参数或环境变量提供，不提交凭据和包含敏感信息的运行日志。
7. 正式 A/B/C 结论必须来自同一真实 provider、冻结题集、完整 JSONL 日志和已完成的人工复核。

## API 文档与兼容性

模型接入步骤统一维护在 [API 使用指南](docs/API_GUIDE.md)，完整实验与导出步骤维护在 [真实实验操作说明](docs/REAL_PILOT_GUIDE.md)。更新示例时应同时检查 CLI 参数和 provider 实际发送的字段，不得把仅在服务商文档中存在、但项目尚未实现的参数写成可用命令。

文档检查不需要调用真实模型。若只核对了请求结构和命令参数，应明确记录“未实际调用付费 API”，不能把该检查表述为模型调用成功。

## 共同作者提交格式

只为实际参与该次修改的人记录共同作者；代码、文档编写或实质性修改均应如实归属，不能仅为徽章填写无关作者。PR 描述中的 `@mention` 不会生成提交共同作者。

提交信息格式如下，正文与末尾声明之间留一个空行：

```text
docs: 补充多模型 API 使用说明

Co-authored-by: Rayleiteng <对方确认的 GitHub 关联邮箱>
```

邮箱应由对方确认，可以是其 GitHub 提供的 noreply 邮箱；不要仅凭用户名推断邮箱。普通邮箱会进入公开提交信息，应优先使用对方同意公开的 noreply 地址。规则见 [GitHub 多作者提交说明](https://docs.github.com/en/pull-requests/how-tos/commit-changes/creating-a-commit-with-multiple-authors)。

### Git Bash 提交示例

在包含本次文档改动的仓库根目录执行。以下示例创建新分支，不修改已经合并的 PR 或提交，不使用强制推送。

```bash
git switch -c codex/api-model-docs
git add -- README.md docs/API_GUIDE.md docs/REAL_PILOT_GUIDE.md docs/methodology.md CONTRIBUTING.md CHANGELOG.md PROGRESS.md
git diff --cached --name-only
git diff --cached --check
```

确认暂存区只有预期的文档；不要使用 `git add .` 将本机显示异常的发布目录删除记录或旧实验一并提交。然后输入对方确认的邮箱：

```bash
read -r -p "Rayleiteng 确认的 GitHub 提交邮箱：" COAUTHOR_EMAIL
if [[ "$COAUTHOR_EMAIL" == *@* ]]; then
  git commit -m "docs: 补充 DeepSeek 与 GPT API 使用指南" -m "Co-authored-by: Rayleiteng <$COAUTHOR_EMAIL>"
else
  printf '%s\n' "邮箱为空或格式不完整，未创建提交。"
fi
unset COAUTHOR_EMAIL
git log -1 --format=full
```

两次 `-m` 会把提交正文与 `Co-authored-by:` 分为两个段落，保留所需空行。上面的简单格式检查不能代替对方确认邮箱归属。只有确认 commit 成功且最新日志确实包含正确署名后，才继续：

```bash
git fetch origin && git merge --no-edit origin/main
```

如果存在合并冲突，先处理并核对，再推送；不要跳过错误继续执行。合并成功后：

```bash
git push -u origin codex/api-model-docs
```

在 GitHub 创建 `codex/api-model-docs` → `main` 的新 PR。合并时保留共同作者声明；如果选择 Squash and merge，应在最终提交信息中检查该声明仍存在。合并后打开提交页面核实作者关联，不把徽章出现时间或是否授予当作可保证的验收结果。
