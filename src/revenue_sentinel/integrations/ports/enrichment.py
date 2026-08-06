"""Enrichment port. Real counterpart: Clearbit or Apollo."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from revenue_sentinel.core.types import JSONObject


@runtime_checkable
class EnrichmentPort(Protocol):
    def get_company_profile(self, *, account_ref: str) -> JSONObject: ...
