# Part 1 基线运行环境（固定 Lean 4.32 + ax-prover）
# 构建： docker build -t axprover-baseline -f baseline/Dockerfile .
# 运行： docker run --rm -it -v "$PWD:/workspace" -e ANTHROPIC_API_KEY=sk-ant-... \
#          axprover-baseline python baseline/run_baseline.py --out runs
FROM leanprover/lean4:v4.32.0

# lean4 镜像自带 lean + lake；补 python3 / pip
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages --no-cache-dir ax-prover pyyaml

WORKDIR /workspace
