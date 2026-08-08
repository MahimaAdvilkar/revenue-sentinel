"""The idempotency key, and why it is shaped the way it is.

The key identifies **an effect**, not an attempt. That single choice is what makes
"re-running the workflow cannot send a second email" true rather than aspirational, and
it is why `run_id` is deliberately absent: keyed by run, a second run would compute a
different key and happily produce a second draft, which is exactly the failure this
exists to prevent.

Included -- all persisted business values, none derived from process state:

* `incident_ref`   -- the same action for a different incident is a different effect
* `action_type`    -- creating a task and drafting an email are different effects
* `target_ref`     -- the account or opportunity acted upon
* `arguments_digest` -- the payload, canonicalised

Excluded, deliberately: `run_id`, `intervention_id`, every timestamp, `attempt_count`,
and every runtime-generated UUID. Nothing here reads a clock or depends on insertion
order, so the key is identical across retries, across process restarts, and across
machines.

See ADR-0017 for the ordering rule that gives the key its force: **the row is claimed
before the effect is performed**, never after.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from revenue_sentinel.core.types import JSONObject
from revenue_sentinel.domain.enums import ActionType

KEY_VERSION: Final = "idem/v1"
"""Part of the hashed payload. If the key's *definition* ever changes, previously
executed effects must not silently collide with newly computed ones -- bumping this
makes the discontinuity explicit instead of producing duplicates on deploy day."""


def canonical_digest(payload: JSONObject) -> str:
    """A stable digest of a JSON object: sorted keys, no incidental whitespace."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def idempotency_key(
    *, incident_ref: str, action_type: ActionType, target_ref: str, arguments: JSONObject
) -> str:
    """The key for one effect. Same effect, same key, forever."""
    return canonical_digest(
        {
            "version": KEY_VERSION,
            "incident_ref": incident_ref,
            "action_type": action_type.value,
            "target_ref": target_ref,
            "arguments_digest": canonical_digest(arguments),
        }
    )
