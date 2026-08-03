"""Domain model validation.

The interesting cases are the ones that keep a bad value out of the database in the
first place: naive datetimes, floats standing in for money, references that do not
match their pattern, and cross-field states that should not be representable.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from revenue_sentinel.domain.enums import (
    AccountSegment,
    ActionStatus,
    ActionType,
    ApprovalStatus,
    BudgetPeriod,
    BudgetScope,
    ComputedBy,
    CostType,
    IncidentStatus,
    IncidentType,
    OpportunityStage,
    PolicyDecision,
    RiskTier,
    Severity,
    TrustLevel,
)
from revenue_sentinel.domain.events import EventEnvelope
from revenue_sentinel.domain.governance import ActionRecord, ApprovalRequest, PolicyEvaluation
from revenue_sentinel.domain.gtm import Account, Opportunity
from revenue_sentinel.domain.incidents import Incident
from revenue_sentinel.domain.investigation import ImpactAssessment
from revenue_sentinel.domain.observability import Budget, CostEntry

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64


def an_account(**overrides: object) -> Account:
    payload: dict[str, object] = {
        "id": uuid4(),
        "account_ref": "ACC-1001",
        "name": "Northwind Logistics",
        "segment": AccountSegment.MID_MARKET,
        "industry": "Transportation & Logistics",
        "employee_count": 850,
        "owner_id": "USR-77",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return Account.model_validate(payload)


def an_opportunity(**overrides: object) -> Opportunity:
    payload: dict[str, object] = {
        "id": uuid4(),
        "opportunity_ref": "OPP-2001",
        "account_id": uuid4(),
        "name": "Platform Expansion",
        "stage": OpportunityStage.PROPOSAL,
        "amount": Decimal("180000.00"),
        "currency": "USD",
        "expected_close_date": date(2026, 9, 15),
        "probability": Decimal("0.6000"),
        "owner_id": "USR-77",
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return Opportunity.model_validate(payload)


# ---------------------------------------------------------------------------
# Money and time
# ---------------------------------------------------------------------------
def test_money_is_decimal_not_float() -> None:
    assert isinstance(an_opportunity().amount, Decimal)


def test_a_float_amount_does_not_silently_become_a_float_field() -> None:
    """Pydantic will coerce, but the stored value must still be a Decimal."""
    opportunity = an_opportunity(amount=180000.5)
    assert isinstance(opportunity.amount, Decimal)
    assert not isinstance(opportunity.amount, float)


def test_negative_amount_is_rejected() -> None:
    with pytest.raises(ValidationError):
        an_opportunity(amount=Decimal("-1.00"))


@pytest.mark.parametrize("bad", [Decimal("-0.0001"), Decimal("1.0001")])
def test_probability_outside_zero_to_one_is_rejected(bad: Decimal) -> None:
    with pytest.raises(ValidationError):
        an_opportunity(probability=bad)


def test_naive_datetime_is_rejected_rather_than_assumed_utc() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        an_account(created_at=datetime(2026, 8, 1, 12, 0))  # noqa: DTZ001 -- the point of the test


def test_aware_datetime_is_normalised_to_utc() -> None:
    tokyo = datetime(2026, 8, 1, 21, 0, tzinfo=timezone(timedelta(hours=9)))
    account = an_account(created_at=tokyo)
    assert account.created_at.tzinfo is UTC
    assert account.created_at == NOW


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------
def test_models_are_frozen() -> None:
    account = an_account()
    with pytest.raises(ValidationError):
        account.name = "Renamed"  # type: ignore[misc]


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        an_account(unexpected_field="value")


# ---------------------------------------------------------------------------
# Business references
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["ACC-1", "ACC1001", "acc-1001", "ACC-10011", "", "ACCOUNT-1001"])
def test_malformed_account_reference_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        an_account(account_ref=bad)


def test_well_formed_references_are_accepted() -> None:
    assert an_account(account_ref="ACC-9999").account_ref == "ACC-9999"
    assert an_opportunity(opportunity_ref="OPP-2001").opportunity_ref == "OPP-2001"


@pytest.mark.parametrize("bad", ["usd", "US", "USDD", "1SD"])
def test_currency_must_be_iso_4217(bad: str) -> None:
    with pytest.raises(ValidationError):
        an_opportunity(currency=bad)


# ---------------------------------------------------------------------------
# Trust level -- rule 14
# ---------------------------------------------------------------------------
def test_trust_level_has_exactly_one_member() -> None:
    """There is no representable 'trusted' ingested content."""
    assert list(TrustLevel) == [TrustLevel.UNTRUSTED]


def test_event_envelope_defaults_to_untrusted() -> None:
    envelope = an_envelope()
    assert envelope.trust_level is TrustLevel.UNTRUSTED


def test_event_envelope_rejects_a_trusted_marking() -> None:
    with pytest.raises(ValidationError):
        an_envelope(trust_level="trusted")


def an_envelope(**overrides: object) -> EventEnvelope:
    from revenue_sentinel.domain.enums import EventType, SourceSystem

    payload: dict[str, object] = {
        "id": uuid4(),
        "raw_event_id": uuid4(),
        "event_type": EventType.CRM_ACTIVITY_LOGGED,
        "source_system": SourceSystem.CRM,
        "occurred_at": NOW,
        "received_at": NOW,
        "account_ref": "ACC-1001",
        "attributes": {"nested": {"list": [1, 2, None]}},
    }
    payload.update(overrides)
    return EventEnvelope.model_validate(payload)


def test_json_attributes_accept_recursive_structures() -> None:
    envelope = an_envelope(attributes={"a": [1, {"b": [True, None, "x"]}], "c": 1.5})
    assert envelope.attributes["c"] == 1.5


# ---------------------------------------------------------------------------
# Cross-field invariants
# ---------------------------------------------------------------------------
def an_incident(**overrides: object) -> Incident:
    payload: dict[str, object] = {
        "id": uuid4(),
        "incident_ref": "INC-001",
        "signal_id": uuid4(),
        "incident_type": IncidentType.STALLED_OPPORTUNITY,
        "status": IncidentStatus.INVESTIGATING,
        "severity": Severity.HIGH,
        "account_id": uuid4(),
        "opened_at": NOW,
        "title": "Northwind Logistics stalled at proposal",
    }
    payload.update(overrides)
    return Incident.model_validate(payload)


def test_open_incident_must_not_carry_a_closed_timestamp() -> None:
    with pytest.raises(ValidationError, match="must not set closed_at"):
        an_incident(status=IncidentStatus.INVESTIGATING, closed_at=NOW)


def test_terminal_incident_requires_a_closed_timestamp() -> None:
    with pytest.raises(ValidationError, match="requires closed_at"):
        an_incident(status=IncidentStatus.COMPLETED)


def test_terminal_incident_with_closure_is_valid_and_reports_terminal() -> None:
    incident = an_incident(status=IncidentStatus.COMPLETED, closed_at=NOW)
    assert incident.is_terminal is True


def test_impact_assessment_rejects_at_risk_above_weighted() -> None:
    with pytest.raises(ValidationError, match="at_risk_value exceeds weighted_value"):
        ImpactAssessment.model_validate(
            {
                "id": uuid4(),
                "run_id": uuid4(),
                "method_version": "pipeline_impact/v1",
                "pipeline_value": Decimal("180000.00"),
                "weighted_value": Decimal("108000.00"),
                "at_risk_value": Decimal("120000.00"),
                "currency": "USD",
                "inputs": {},
                "computed_by": ComputedBy.DETERMINISTIC,
            }
        )


def test_cost_entry_must_name_exactly_one_source() -> None:
    base: dict[str, object] = {
        "id": uuid4(),
        "run_id": uuid4(),
        "cost_type": CostType.MODEL_INFERENCE,
        "amount_usd": Decimal("0.001234"),
        "pricing_version": "2026-08",
        "recorded_at": NOW,
    }
    with pytest.raises(ValidationError, match="exactly one"):
        CostEntry.model_validate(base)
    with pytest.raises(ValidationError, match="exactly one"):
        CostEntry.model_validate({**base, "model_call_id": uuid4(), "tool_call_id": uuid4()})

    entry = CostEntry.model_validate({**base, "model_call_id": uuid4()})
    assert entry.tool_call_id is None


def test_policy_evaluation_must_name_a_matched_rule() -> None:
    with pytest.raises(ValidationError, match="at least one matched rule"):
        PolicyEvaluation.model_validate(
            {
                "id": uuid4(),
                "intervention_id": uuid4(),
                "policy_version": "v1",
                "risk_tier": RiskTier.INTERNAL_REVERSIBLE,
                "decision": PolicyDecision.ALLOW,
                "matched_rules": (),
                "reason": "no rule matched",
                "evaluated_at": NOW,
            }
        )


def an_approval(**overrides: object) -> ApprovalRequest:
    payload: dict[str, object] = {
        "id": uuid4(),
        "policy_evaluation_id": uuid4(),
        "run_id": uuid4(),
        "status": ApprovalStatus.PENDING,
        "requested_at": NOW,
        "expires_at": NOW + timedelta(hours=72),
    }
    payload.update(overrides)
    return ApprovalRequest.model_validate(payload)


def test_approval_expiry_must_follow_the_request() -> None:
    with pytest.raises(ValidationError, match="expires_at must be after"):
        an_approval(expires_at=NOW - timedelta(hours=1))


def test_decided_approval_requires_a_decider() -> None:
    with pytest.raises(ValidationError, match="requires decided_at and decided_by"):
        an_approval(status=ApprovalStatus.APPROVED)


def test_pending_approval_must_not_carry_a_decider() -> None:
    with pytest.raises(ValidationError, match="must not carry a decider"):
        an_approval(decided_at=NOW, decided_by="user:USR-77")


def test_expired_approval_needs_no_decider() -> None:
    """Nobody decided anything; the window simply elapsed."""
    approval = an_approval(status=ApprovalStatus.EXPIRED)
    assert approval.decided_by is None


def test_succeeded_action_requires_an_execution_timestamp() -> None:
    with pytest.raises(ValidationError, match="requires executed_at"):
        ActionRecord.model_validate(
            {
                "id": uuid4(),
                "run_id": uuid4(),
                "intervention_id": uuid4(),
                "action_type": ActionType.CRM_TASK,
                "target_ref": "OPP-2001",
                "idempotency_key": DIGEST,
                "status": ActionStatus.SUCCEEDED,
                "authorized_by": uuid4(),
                "attempt_count": 1,
            }
        )


def test_idempotency_key_must_be_a_sha256_digest() -> None:
    with pytest.raises(ValidationError):
        ActionRecord.model_validate(
            {
                "id": uuid4(),
                "run_id": uuid4(),
                "intervention_id": uuid4(),
                "action_type": ActionType.CRM_TASK,
                "target_ref": "OPP-2001",
                "idempotency_key": "not-a-digest",
                "status": ActionStatus.PENDING,
                "authorized_by": uuid4(),
                "attempt_count": 0,
            }
        )


def test_scoped_budget_requires_a_scope_reference() -> None:
    with pytest.raises(ValidationError, match="requires a scope_ref"):
        Budget.model_validate(
            {
                "id": uuid4(),
                "scope": BudgetScope.RUN,
                "period": BudgetPeriod.RUN,
                "limit_usd": Decimal("0.50"),
                "consumed_usd": Decimal("0.00"),
                "hard_stop": True,
            }
        )


def test_global_budget_needs_no_scope_reference_and_reports_remaining() -> None:
    budget = Budget.model_validate(
        {
            "id": uuid4(),
            "scope": BudgetScope.GLOBAL,
            "period": BudgetPeriod.MONTHLY,
            "limit_usd": Decimal("25.00"),
            "consumed_usd": Decimal("4.25"),
            "hard_stop": True,
        }
    )
    assert budget.remaining_usd == Decimal("20.75")
    assert budget.is_exhausted is False
