#!/usr/bin/env bash
set -euo pipefail

PROJECT="${1:-$(dirname "$0")/../mathlib_project}"
cd "$PROJECT"
PROJECT="$(pwd -P)"
MAX_ATTEMPTS="${TRACER_SETUP_ATTEMPTS:-3}"
RETRY_DELAY="${TRACER_SETUP_RETRY_DELAY:-5}"

# 有限重试用于应对临时网络故障；不修改 Git 全局配置或关闭证书校验。
if [[ ! "$MAX_ATTEMPTS" =~ ^[1-5]$ ]] || [[ ! "$RETRY_DELAY" =~ ^([0-9]|[12][0-9]|30)$ ]]; then
  echo "重试次数必须为 1–5，初始等待必须为 0–30 秒。" >&2
  exit 2
fi
command -v lake >/dev/null || { echo "找不到 lake，请先安装 Lean 工具链。" >&2; exit 127; }
command -v git >/dev/null || { echo "找不到 git。" >&2; exit 127; }

check_managed_paths() {
  local path
  for path in "$PROJECT/.lake" "$PROJECT/.lake/packages" "$PROJECT/.lake/retry-backups"; do
    if [[ -L "$path" ]]; then
      echo "拒绝自动恢复符号链接目录：$path" >&2
      return 2
    fi
  done
}

recover_incomplete_packages() {
  local package resolved backup
  check_managed_paths || return $?
  [[ -d "$PROJECT/.lake/packages" ]] || return 0
  for package in "$PROJECT/.lake/packages/"*; do
    # 只处理包自己的普通 Git 目录，不移动链接、worktree 或无 Git 的本地依赖。
    [[ -d "$package" && ! -L "$package" && -d "$package/.git" && ! -L "$package/.git" ]] || continue
    if git -C "$package" rev-parse --verify 'HEAD^{commit}' >/dev/null 2>&1; then
      continue
    fi
    resolved="$(cd "$package" && pwd -P)" || return $?
    if [[ "$resolved" != "$package" ]]; then
      echo "依赖目录解析结果不在预期位置，停止自动恢复：$package" >&2
      return 2
    fi
    # 残缺克隆可能来自任意传递依赖；移动到可恢复备份，不删除用户数据。
    mkdir -p "$PROJECT/.lake/retry-backups" || return $?
    backup="$(mktemp -d "$PROJECT/.lake/retry-backups/package.XXXXXX")" || return $?
    mv -- "$resolved" "$backup/$(basename "$package")" || return $?
    echo "已备份无有效 HEAD 的依赖：$backup/$(basename "$package")"
  done
}

run_with_retry() {
  local label="$1" attempt status delay="$RETRY_DELAY"
  shift
  for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    if [[ "$label" == "依赖同步" ]]; then
      recover_incomplete_packages || return $?
    fi
    echo "${label}：第 $attempt/$MAX_ATTEMPTS 次尝试"
    if "$@"; then
      return 0
    else
      status=$?
    fi
    if ((attempt == MAX_ATTEMPTS)); then
      echo "$label 重试耗尽，退出码：${status}；请检查网络或上方错误，不会跳过验证。" >&2
      return "$status"
    fi
    echo "$label 失败（退出码 ${status}），${delay} 秒后重试..." >&2
    sleep "$delay"
    delay=$((delay * 2))
    if ((delay > 60)); then delay=60; fi
  done
}

check_managed_paths
export MATHLIB_CACHE_DIR="${MATHLIB_CACHE_DIR:-$PROJECT/.lake/mathlib-cache}"
mkdir -p "$MATHLIB_CACHE_DIR"
echo "正在同步 Mathlib 依赖..."
run_with_retry "依赖同步" lake update
if [ ! -f ".lake/packages/mathlib/.lake/build/lib/lean/Mathlib.olean" ]; then
  echo "正在获取 Mathlib 预编译缓存..."
  run_with_retry "预编译缓存下载" lake exe cache get
fi
echo "Mathlib 环境准备完成。"
