"""根目录兼容入口，同时暴露 src/leancapsule 的公共 API。"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
IMPLEMENTATION = SOURCE_ROOT / "leancapsule"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))
if str(IMPLEMENTATION) not in __path__:
    __path__.append(str(IMPLEMENTATION))

from .diagnostics_key import diagnostic_key
from .feedback import CapsuleFeedback, normalized_feedback_text
from .ax_integration import (
    CapsuleFeedbackSessions,
    FEEDBACK_MODES,
    FirstRoundCandidateCache,
    enforce_ax_part2_config,
    install_axproverbase_capsule_feedback,
    RawFeedbackTracker,
    validate_ax_proposal_safety,
)
from .pairing import validate_paired_runs
from .part3 import build_summary, validate_part3_runs, write_part3_outputs

__all__ = [
    "CapsuleFeedback",
    "CapsuleFeedbackSessions",
    "FEEDBACK_MODES",
    "FirstRoundCandidateCache",
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
]
