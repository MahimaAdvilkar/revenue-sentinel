"""Product-usage port. Real counterpart: a warehouse query or Segment."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject


@runtime_checkable
class ProductPort(Protocol):
    def get_usage_summary(
        self, *, account_ref: str, period_start: date, period_end: date
    ) -> JSONObject: ...
