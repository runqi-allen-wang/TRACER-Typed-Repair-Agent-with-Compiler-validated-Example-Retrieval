"""可读的证明输出与验收协议；版本变化不回写历史轨迹。"""

PROOF_PROTOCOL = {
    "version": "tracer-proof-v2",
    "replacement": "whole-proof-region",
    "compilation": "kernel-with-warnings-recorded",
    "incomplete_proof": "reject",
    "truncated_generation": "reject-before-compile",
}

LEGACY_PROTOCOL_VERSION = "legacy-strict-warnings-v1"
