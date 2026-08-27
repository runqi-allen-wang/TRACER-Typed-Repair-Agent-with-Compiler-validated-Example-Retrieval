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
