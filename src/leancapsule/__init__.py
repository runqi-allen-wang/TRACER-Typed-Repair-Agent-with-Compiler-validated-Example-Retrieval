"""LeanCapsule：可复现、可回放的 Lean 失败工件工具。"""

from .diagnostics_key import diagnostic_key
from .feedback import CapsuleFeedback, normalized_feedback_text
from .ax_integration import (
    CapsuleFeedbackSessions,
    FEEDBACK_MODES,
    FirstRoundCandidateCache,
    MEMORY_CLASSES,
    enforce_ax_part2_config,
    install_axproverbase_capsule_feedback,
    RawFeedbackTracker,
    validate_ax_proposal_safety,
)
from .pairing import validate_experience_capsule_pair, validate_paired_runs
from .part3 import build_summary, validate_part3_runs, write_part3_outputs

__all__ = [
    "CapsuleFeedback",
    "CapsuleFeedbackSessions",
    "FEEDBACK_MODES",
    "FirstRoundCandidateCache",
    "MEMORY_CLASSES",
    "build_summary",
    "diagnostic_key",
    "enforce_ax_part2_config",
    "install_axproverbase_capsule_feedback",
    "normalized_feedback_text",
    "RawFeedbackTracker",
    "validate_part3_runs",
    "write_part3_outputs",
    "validate_ax_proposal_safety",
    "validate_paired_runs",
    "validate_experience_capsule_pair",
]
