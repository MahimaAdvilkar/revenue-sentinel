"""CRM port. Real counterpart: HubSpot or Salesforce."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject


@runtime_checkable
class CrmPort(Protocol):
    """Read and write access to customer and deal records."""

    def search_accounts(self, *, query: str, segment: str | None, limit: int) -> JSONObject: ...

    def get_account(self, *, account_ref: str) -> JSONObject: ...

    def get_opportunity(self, *, opportunity_ref: str) -> JSONObject: ...

    def list_account_activities(
        self, *, account_ref: str, since: datetime, limit: int
    ) -> JSONObject: ...

    def create_task(
        self,
        *,
        opportunity_ref: str,
        title: str,
        description: str,
        due_date: date,
        assignee_ref: str,
    ) -> JSONObject: ...

    def update_opportunity(
        self, *, opportunity_ref: str, field_name: str, value: str, reason: str
    ) -> JSONObject: ...
