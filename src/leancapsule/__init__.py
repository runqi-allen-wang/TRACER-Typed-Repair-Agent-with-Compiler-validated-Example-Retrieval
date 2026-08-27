"""LeanCapsule：可复现、可回放的 Lean 失败工件工具。"""

from .diagnostics_key import diagnostic_key
from .feedback import CapsuleFeedback, stable_feedback_fingerprint
from .ax_integration import (
    CapsuleFeedbackSessions,
    FirstRoundCandidateCache,
    enforce_ax_part2_config,
    install_axproverbase_capsule_feedback,
)
from .pairing import candidate_digest, validate_paired_runs

__all__ = [
    "CapsuleFeedback",
    "CapsuleFeedbackSessions",
    "FirstRoundCandidateCache",
    "candidate_digest",
    "diagnostic_key",
    "enforce_ax_part2_config",
    "install_axproverbase_capsule_feedback",
    "stable_feedback_fingerprint",
    "validate_paired_runs",
]
