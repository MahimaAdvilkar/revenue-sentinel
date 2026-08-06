"""Support port. Real counterpart: Zendesk or Intercom."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject


@runtime_checkable
class SupportPort(Protocol):
    def get_open_issues(self, *, account_ref: str) -> JSONObject: ...
