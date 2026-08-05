"""`RepositoryEvidenceSource` -- the Session 3 implementation of the evidence port.

Reads the seeded GTM mirror through `db/` repositories. It lives here rather than in
`agents/` because `agents/` may not import `db/` (boundary R5): the agent holds the
port, this holds the plumbing.

> **Session 4 replaces this class and nothing else.** Each method corresponds to one
> MCP tool with the same name and arguments, so the swap is a different implementation
> behind the same port -- not a redesign of the researcher.

Each method returns a tuple, because one call can yield several distinct facts. The
usage summary decomposes into one record per weekly period: two adjacent weeks are two
pieces of evidence a hypothesis may cite separately, not one blob.

Returned `content` is untrusted (rule 14). Free-text fields are carried verbatim,
never sanitised -- sanitising here would hide adversarial content from the audit trail
while doing nothing about containment, which is delimiting at render time and the
policy layer at decision time.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.orm import Session

from revenue_sentinel.agents.ports import EvidenceRecord
from revenue_sentinel.analytics.windows import week_over_week_growth
from revenue_sentinel.core.errors import CalculationError, NotFoundError
from revenue_sentinel.db.repositories import (
    AccountRepository,
    ActivityRepository,
    EngagementEventRepository,
    OpportunityRepository,
    SupportIssueRepository,
    UsageSnapshotRepository,
)
from revenue_sentinel.domain.enums import SourceSystem

DEFAULT_ACTIVITY_LIMIT: Final = 10
OPEN_ISSUE_STATUSES: Final = frozenset({"open", "pending"})


class RepositoryEvidenceSource:
    """Evidence from the local mirror. Read-only."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_opportunity(self, opportunity_id: UUID) -> tuple[EvidenceRecord, ...]:
        opportunity = OpportunityRepository(self._session).get_by_id(opportunity_id)
        if opportunity is None:
            raise NotFoundError("opportunity", str(opportunity_id))
        account = AccountRepository(self._session).get_by_id(opportunity.account_id)

        return (
            EvidenceRecord(
                source_system=SourceSystem.CRM,
                tool_name="crm_get_opportunity",
                content={
                    "opportunity_ref": opportunity.opportunity_ref,
                    "name": opportunity.name,
                    "account": account.name if account else None,
                    "stage": opportunity.stage.value,
                    "amount": str(opportunity.amount),
                    "currency": opportunity.currency,
                    "probability": str(opportunity.probability),
                    "expected_close_date": opportunity.expected_close_date.isoformat(),
                    "owner_id": opportunity.owner_id,
                    "is_simulated": opportunity.is_simulated,
                },
            ),
        )

    def list_account_activities(
        self, account_id: UUID, *, limit: int = DEFAULT_ACTIVITY_LIMIT
    ) -> tuple[EvidenceRecord, ...]:
        activities = ActivityRepository(self._session).list_for_account(account_id)[:limit]
        return (
            EvidenceRecord(
                source_system=SourceSystem.CRM,
                tool_name="crm_list_account_activities",
                content={
                    "count": len(activities),
                    "most_recent_first": [
                        {
                            "type": activity.activity_type.value,
                            "direction": activity.direction.value,
                            "occurred_at": activity.occurred_at.isoformat(),
                            # Untrusted free text, verbatim.
                            "subject": activity.subject,
                            "body": activity.body,
                        }
                        for activity in activities
                    ],
                },
            ),
        )

    def get_usage_summary(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        """One record per weekly period.

        The most recent period carries the week-over-week growth, so a hypothesis can
        cite "the week that grew" rather than "the usage blob".
        """
        snapshots = UsageSnapshotRepository(self._session).list_for_account(account_id)

        records: list[EvidenceRecord] = []
        for index, snapshot in enumerate(snapshots):
            growth: str | None = None
            if index > 0:
                try:
                    growth = str(
                        week_over_week_growth(
                            earlier=snapshots[index - 1].feature_events,
                            later=snapshot.feature_events,
                        )
                    )
                except CalculationError:
                    growth = None

            records.append(
                EvidenceRecord(
                    source_system=SourceSystem.PRODUCT,
                    tool_name="product_get_usage_summary",
                    content={
                        "period_start": snapshot.period_start.isoformat(),
                        "period_end": snapshot.period_end.isoformat(),
                        "active_users": snapshot.active_users,
                        "sessions": snapshot.sessions,
                        "feature_events": snapshot.feature_events,
                        "usage_score": str(snapshot.usage_score),
                        "week_over_week_growth": growth,
                    },
                )
            )
        return tuple(records)

    def get_email_activity(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        events = EngagementEventRepository(self._session).list_for_account(account_id)
        counts: dict[str, int] = {}
        for event in events:
            counts[event.event_type.value] = counts.get(event.event_type.value, 0) + 1

        return (
            EvidenceRecord(
                source_system=SourceSystem.ENGAGEMENT,
                tool_name="engagement_get_email_activity",
                content={
                    "totals_by_event_type": dict(sorted(counts.items())),
                    "meetings_held": counts.get("meeting_held", 0),
                    "events": [
                        {
                            "channel": event.channel.value,
                            "event_type": event.event_type.value,
                            "occurred_at": event.occurred_at.isoformat(),
                        }
                        for event in events
                    ],
                },
            ),
        )

    def get_open_issues(self, account_id: UUID) -> tuple[EvidenceRecord, ...]:
        issues = [
            issue
            for issue in SupportIssueRepository(self._session).list_for_account(account_id)
            if issue.status.value in OPEN_ISSUE_STATUSES
        ]
        return (
            EvidenceRecord(
                source_system=SourceSystem.SUPPORT,
                tool_name="support_get_open_issues",
                content={
                    "open_count": len(issues),
                    "issues": [
                        {
                            "external_ref": issue.external_ref,
                            "severity": issue.severity.value,
                            "status": issue.status.value,
                            "opened_at": issue.opened_at.isoformat(),
                            # Untrusted free text, verbatim.
                            "summary": issue.summary,
                        }
                        for issue in issues
                    ],
                },
            ),
        )
