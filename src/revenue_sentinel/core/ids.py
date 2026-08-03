"""Identifiers.

Two kinds, deliberately separated:

* **Surrogate keys** -- UUIDs, the `id` column on every table.
* **Business references** -- `ACC-1001`, `OPP-2001`, `INC-001`. Human-readable, shown
  in the UI and spoken aloud in the demo.

Seeded data uses `deterministic_uuid`, which derives a UUIDv5 from the seed plus the
business key. Deriving rather than drawing from a random stream means row identity is
independent of insertion order, so a reordered seeder still produces byte-identical
rows (acceptance criterion 6).
"""

from __future__ import annotations

import re
import uuid
from typing import Final

from revenue_sentinel.core.errors import DomainValidationError

REF_PATTERN: Final = re.compile(r"^(?P<prefix>[A-Z]{2,4})-(?P<number>[0-9]{1,6})$")

# Business-reference prefixes used in v1. Listed here so the vocabulary is closed and
# a typo in a fixture fails loudly instead of creating a new entity class by accident.
PREFIX_ACCOUNT: Final = "ACC"
PREFIX_OPPORTUNITY: Final = "OPP"
PREFIX_INCIDENT: Final = "INC"
PREFIX_EVIDENCE: Final = "EV"
PREFIX_HYPOTHESIS: Final = "HYP"
PREFIX_USER: Final = "USR"

_SEED_NAMESPACE_URL: Final = "https://revenue-sentinel.local/seed/{seed}"


def new_id() -> uuid.UUID:
    """A fresh random surrogate key, for rows created at runtime."""
    return uuid.uuid4()


def deterministic_uuid(seed: int, *parts: str) -> uuid.UUID:
    """Derive a stable UUID from a seed and a business key.

    Same seed and same parts always yield the same UUID; a different seed yields a
    different one. Used exclusively by the seeder.
    """
    if not parts:
        raise DomainValidationError("deterministic_uuid requires at least one key part")
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, _SEED_NAMESPACE_URL.format(seed=seed))
    return uuid.uuid5(namespace, "|".join(parts))


def format_ref(prefix: str, number: int, *, width: int) -> str:
    """Render a business reference, e.g. ``format_ref("ACC", 1001, width=4)``."""
    if number < 0:
        raise DomainValidationError(f"business reference number must be non-negative: {number}")
    ref = f"{prefix}-{number:0{width}d}"
    if not REF_PATTERN.match(ref):
        raise DomainValidationError(f"malformed business reference: {ref!r}")
    return ref


def parse_ref(ref: str) -> tuple[str, int]:
    """Split a business reference into its prefix and number.

    Raises on anything that is not a well-formed reference -- ingested content is
    untrusted (rule 14), so a reference arriving from a fixture or an external system
    is validated rather than assumed.
    """
    match = REF_PATTERN.match(ref)
    if match is None:
        raise DomainValidationError(f"malformed business reference: {ref!r}")
    return match.group("prefix"), int(match.group("number"))


def account_ref(number: int) -> str:
    """`ACC-1001`."""
    return format_ref(PREFIX_ACCOUNT, number, width=4)


def opportunity_ref(number: int) -> str:
    """`OPP-2001`."""
    return format_ref(PREFIX_OPPORTUNITY, number, width=4)


def incident_ref(number: int) -> str:
    """`INC-001`."""
    return format_ref(PREFIX_INCIDENT, number, width=3)


def evidence_ref(number: int) -> str:
    """`EV-003`."""
    return format_ref(PREFIX_EVIDENCE, number, width=3)


def hypothesis_ref(number: int) -> str:
    """`HYP-001`."""
    return format_ref(PREFIX_HYPOTHESIS, number, width=3)
