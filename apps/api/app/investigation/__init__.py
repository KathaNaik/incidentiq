"""Evidence-backed incident investigation.

The only place in IncidentIQ where a language model runs. It is given a fixed set of
typed evidence, asked for ranked hypotheses that cite that evidence by id, and its answer
is validated against the registry before anyone sees it. It recommends; it never acts.
"""

from app.investigation.evidence import EvidenceRegistry, build_registry
from app.investigation.models import (
    EvidenceItem,
    EvidenceKind,
    Hypothesis,
    InvestigationOutput,
    InvestigationResult,
    InvestigationRun,
    NextStepAction,
    RecommendedNextStep,
    RemediationAction,
    RemediationRecommendation,
    RiskLevel,
)
from app.investigation.prompt import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_user_message,
    select_prompt,
)
from app.investigation.prompt_v2 import PROMPT_VERSION_V2, SYSTEM_PROMPT_V2
from app.investigation.provider import (
    InvestigationModel,
    InvestigationModelError,
    ModelResponse,
    OpenAIInvestigationModel,
)
from app.investigation.rules import HISTORICAL_EVIDENCE_K, INVESTIGATION_VERSION
from app.investigation.service import DEFAULT_PROMPT_VERSION, collect_evidence, investigate
from app.investigation.tools import ToolError, load_operations
from app.investigation.validate import InvestigationValidationError, validate_output

__all__ = [
    "HISTORICAL_EVIDENCE_K",
    "DEFAULT_PROMPT_VERSION",
    "INVESTIGATION_VERSION",
    "PROMPT_VERSION",
    "PROMPT_VERSION_V2",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_V2",
    "EvidenceItem",
    "EvidenceKind",
    "EvidenceRegistry",
    "Hypothesis",
    "InvestigationModel",
    "InvestigationModelError",
    "InvestigationOutput",
    "InvestigationResult",
    "InvestigationRun",
    "InvestigationValidationError",
    "ModelResponse",
    "NextStepAction",
    "OpenAIInvestigationModel",
    "RecommendedNextStep",
    "RemediationAction",
    "RemediationRecommendation",
    "RiskLevel",
    "ToolError",
    "build_registry",
    "build_user_message",
    "collect_evidence",
    "investigate",
    "load_operations",
    "select_prompt",
    "validate_output",
]
