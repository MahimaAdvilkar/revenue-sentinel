"""Engagement port. Real counterpart: Gmail or Outlook plus a calendar API."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject


@runtime_checkable
class EngagementPort(Protocol):
    def get_email_activity(self, *, account_ref: str, since: datetime) -> JSONObject: ...

    def get_meeting_activity(self, *, account_ref: str, since: datetime) -> JSONObject: ...
