# Part1 基线运行环境：ubuntu + elan(Lean 4.32) + ax-prover
# 说明：Lean 官方"镜像"在 Docker Hub/GHCR 拉取不稳定（leanprover/lean4 拉不到、ghcr denied），
#   故改用 ubuntu 基础镜像 + elan 安装 lean 4.32.0，避免依赖官方镜像。
# 构建： docker build -t axprover-baseline -f baseline/Dockerfile .
# 运行： docker run --rm -it -v "$PWD:/workspace" \
#          -e OPENAI_API_KEY=sk-... axprover-baseline bash
#   之后在容器里：cd fate_v432 && lake exe cache get && lake build
#   再：python baseline/run_api.py ...
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV http_proxy=http://host.docker.internal:7897 \
    https_proxy=http://host.docker.internal:7897 \
    no_proxy=localhost,127.0.0.1,host.docker.internal

# 基础工具 + python + git（apt 用国内清华源，直连；不走代理）
RUN set -eux; \
    sed -i 's@http://archive.ubuntu.com/ubuntu/@http://mirrors.tuna.tsinghua.edu.cn/ubuntu/@g' \
        /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true; \
    sed -i 's@http://security.ubuntu.com/ubuntu/@http://mirrors.tuna.tsinghua.edu.cn/ubuntu/@g' \
        /etc/apt/sources.list.d/ubuntu.sources 2>/dev/null || true; \
    unset http_proxy https_proxy; \
    apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git python3 python3-pip python3-venv build-essential \
    && rm -rf /var/lib/apt/lists/*

# 直接用 Lean 官方 Linux 二进制（自带 lean + lake，绕开 elan 下载失败）
RUN apt-get update && apt-get install -y --no-install-recommends zstd && rm -rf /var/lib/apt/lists/*
RUN curl -sSfL https://releases.lean-lang.org/lean4/v4.32.0/lean-4.32.0-linux.tar.zst -o /tmp/lean.tzst \
    && tar --zstd -xf /tmp/lean.tzst -C /usr/local \
    && ln -s /usr/local/lean-4.32.0-linux/bin/lean /usr/local/bin/lean \
    && ln -s /usr/local/lean-4.32.0-linux/bin/lake /usr/local/bin/lake

# ax-prover + 依赖
RUN pip3 install --break-system-packages --no-cache-dir ax-prover pyyaml

WORKDIR /workspace
