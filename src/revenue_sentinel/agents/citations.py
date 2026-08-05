"""The anti-hallucination gate.

A hypothesis that cites evidence which does not exist is rejected before anything is
persisted. It never reaches the database, and therefore never reaches a screen.

This is one of two layers. The other is structural: `hypothesis_evidence` has foreign
keys to both `hypotheses` and `evidence_items`, so a fabricated reference has no row
to point at even if this check were bypassed. Belt and constraint.

Kept in its own module because it is the check the demo makes a claim about out loud,
and a claim worth making is worth being able to point at.
"""

from __future__ import annotations

from revenue_sentinel.core.errors import FabricatedCitationError
from revenue_sentinel.intelligence.schemas import HypothesisSet


def validate_citations(hypotheses: HypothesisSet, known_refs: frozenset[str]) -> None:
    """Raise unless every citation names evidence that is actually in state.

    Checks every hypothesis rather than stopping at the first failure, so the error
    names all of the fabricated references at once -- one round trip for whoever is
    debugging a prompt, not one per bad citation.

    Raises:
        FabricatedCitationError: naming the first offending hypothesis and every
            unknown reference it cited.
    """
    for hypothesis in sorted(hypotheses.hypotheses, key=lambda item: item.rank):
        unknown = tuple(ref for ref in hypothesis.cites if ref not in known_refs)
        if unknown:
            raise FabricatedCitationError(f"hypothesis rank {hypothesis.rank}", unknown)
