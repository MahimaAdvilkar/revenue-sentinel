"""Workflow state.

Explicitly typed, no `dict[str, Any]` anywhere (`docs/agent-architecture.md` §3).

Fields for `interventions`, `policy_decisions`, `actions`, and `evaluation_result`
are **deliberately absent**. They arrive in Sessions 5 and 6. A typed field that
nothing writes is a claim the graph does something it does not, and the state model is
the first place a reader looks to find out what the workflow actually does.

`state_digest` hashes a canonical serialisation, so two runs over identical inputs
produce identical digests and a transition's recorded digest is checkable rather than
decorative.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from revenue_sentinel.agents.researcher import GatheredEvidence
from revenue_sentinel.analytics.pipeline_impact import PipelineImpact
from revenue_sentinel.domain.gtm import Account, Opportunity
from revenue_sentinel.domain.incidents import Incident
from revenue_sentinel.intelligence.schemas import HypothesisSet, InvestigationPlan


@dataclass(frozen=True, slots=True)
class WorkflowState:
    """Everything the investigation graph knows.

    Frozen. Nodes return a new state rather than mutating one, so a node cannot
    quietly affect a sibling and every transition digest describes a real snapshot.
    """

    run_id: UUID
    incident_id: UUID
    incident: Incident
    account: Account
    opportunity: Opportunity
    evaluated_at: datetime
    days_inactive: int
    usage_growth: str

    plan: InvestigationPlan | None = None
    evidence: tuple[GatheredEvidence, ...] = field(default_factory=tuple)
    hypotheses: HypothesisSet | None = None
    impact: PipelineImpact | None = None

    def with_plan(self, plan: InvestigationPlan) -> WorkflowState:
        return replace(self, plan=plan)

    def with_evidence(self, evidence: tuple[GatheredEvidence, ...]) -> WorkflowState:
        return replace(self, evidence=evidence)

    def with_hypotheses(self, hypotheses: HypothesisSet) -> WorkflowState:
        return replace(self, hypotheses=hypotheses)

    def with_impact(self, impact: PipelineImpact) -> WorkflowState:
        return replace(self, impact=impact)

    @property
    def known_evidence_refs(self) -> frozenset[str]:
        """The references a hypothesis is allowed to cite."""
        return frozenset(item.evidence_ref for item in self.evidence)

    def digest(self) -> str:
        """`sha256` over a canonical view of the state.

        Deliberately excludes nothing that a node can change, and includes nothing a
        node cannot -- so a digest that differs between runs means the workflow
        genuinely diverged.
        """
        snapshot = {
            "run_id": str(self.run_id),
            "incident_ref": self.incident.incident_ref,
            "evaluated_at": self.evaluated_at.isoformat(),
            "days_inactive": self.days_inactive,
            "usage_growth": self.usage_growth,
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "evidence": [
                {
                    "ref": item.evidence_ref,
                    "source": item.record.source_system.value,
                    "tool": item.record.tool_name,
                    "content": item.record.content,
                }
                for item in self.evidence
            ],
            "hypotheses": (self.hypotheses.model_dump(mode="json") if self.hypotheses else None),
            "impact": self.impact.model_dump(mode="json") if self.impact else None,
        }
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
