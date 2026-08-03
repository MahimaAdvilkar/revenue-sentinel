"""Every table in the schema, re-exported.

Alembic's `env.py` imports this package so that `Base.metadata` is fully populated
before autogenerate runs. A model that is not reachable from here is invisible to
migrations -- which is why the export list is explicit rather than a wildcard.

29 tables, matching `docs/data-model.md` §3.
"""

from __future__ import annotations

from revenue_sentinel.db.base import Base
from revenue_sentinel.db.models.evaluation import EvaluationResult, EvaluationRun
from revenue_sentinel.db.models.events import NormalizedEvent, RawEvent, Signal
from revenue_sentinel.db.models.governance import (
    ActionRecord,
    ApprovalRequest,
    PolicyEvaluation,
)
from revenue_sentinel.db.models.gtm import (
    Account,
    Activity,
    CompanyProfile,
    EngagementEvent,
    Opportunity,
    SupportIssue,
    UsageSnapshot,
)
from revenue_sentinel.db.models.investigation import (
    EvidenceItem,
    Hypothesis,
    HypothesisEvidence,
    ImpactAssessment,
    Intervention,
)
from revenue_sentinel.db.models.observability import (
    AuditEvent,
    Budget,
    CostEntry,
    ModelCall,
    ToolCall,
)
from revenue_sentinel.db.models.workflow import (
    AgentDecision,
    Incident,
    WorkflowRun,
    WorkflowTransition,
)

__all__ = [
    "Account",
    "ActionRecord",
    "Activity",
    "AgentDecision",
    "ApprovalRequest",
    "AuditEvent",
    "Base",
    "Budget",
    "CompanyProfile",
    "CostEntry",
    "EngagementEvent",
    "EvaluationResult",
    "EvaluationRun",
    "EvidenceItem",
    "Hypothesis",
    "HypothesisEvidence",
    "ImpactAssessment",
    "Incident",
    "Intervention",
    "ModelCall",
    "NormalizedEvent",
    "Opportunity",
    "PolicyEvaluation",
    "RawEvent",
    "Signal",
    "SupportIssue",
    "ToolCall",
    "UsageSnapshot",
    "WorkflowRun",
    "WorkflowTransition",
]
