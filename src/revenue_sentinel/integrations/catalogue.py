"""The integration catalogue, read out of the adapters themselves.

Every adapter already declares two things that a catalogue needs: `INTEGRATION_STATUS`,
which the MCP server stamps onto every tool result, and a module docstring whose
"What changes when this becomes real" section names the API, the auth model, the rate
limits, and the fields that differ.

**Both are read from the module.** Nothing here is written by hand, and that is the whole
point of putting it in a module of its own: a catalogue maintained separately from the
adapters is a catalogue that can disagree with them, and the disagreement would be
invisible. The screen a reviewer looks at is derived from the code that would actually
serve the request.

## What this can and cannot guarantee

It *can* guarantee that the status shown is the status the adapter declares, and that the
roadmap copy shown is the copy in the adapter's own docstring.

It *cannot* guarantee the docstring survives: `python -O` strips docstrings, and the
section would then be absent. Rather than invent replacement text, `documented` goes
`False` and the UI says the adapter does not document it. A unit test asserts all six
adapters do document it, so the absence is a deployment mode, never a regression.
"""

from __future__ import annotations

import importlib
import re
from dataclasses import dataclass
from types import ModuleType
from typing import Final

from revenue_sentinel.integrations.status import IntegrationStatus, status_of

SECTION_HEADING: Final = "## What changes when this becomes real"

_HEADED_PARAGRAPH: Final = re.compile(r"^\*\*(?P<heading>[^*]+?)\.?\*\*\s*(?P<body>.*)", re.S)


@dataclass(frozen=True, slots=True)
class RoadmapNote:
    """One headed paragraph from an adapter's roadmap section."""

    heading: str
    body: str


@dataclass(frozen=True, slots=True)
class CatalogueEntry:
    """One adapter, as it describes itself."""

    name: str
    module: str
    port: str
    status: IntegrationStatus
    summary: str
    when_real: tuple[RoadmapNote, ...]
    documented: bool


ADAPTERS: Final[tuple[tuple[str, str], ...]] = (
    ("CRM", "crm"),
    ("Product usage", "product"),
    ("Engagement", "engagement"),
    ("Support", "support"),
    ("Enrichment", "enrichment"),
    ("Messaging", "messaging"),
)
"""Display name and module name for every adapter. The *status* is not listed here --
listing it would be exactly the hand-maintained claim this module exists to avoid."""


def _summary(doc: str) -> str:
    """The adapter's first line, with its markdown emphasis removed."""
    first = doc.strip().splitlines()[0] if doc.strip() else ""
    return first.replace("**", "").strip()


def parse_roadmap(doc: str | None) -> tuple[RoadmapNote, ...]:
    """Split an adapter docstring's roadmap section into headed paragraphs.

    Only text *after* the section heading is considered. `messaging.py` carries a bold
    paragraph before the heading ("There is no send method"), and pulling that in would
    misfile a present-tense guarantee as a future change.
    """
    if not doc or SECTION_HEADING not in doc:
        return ()

    section = doc.split(SECTION_HEADING, 1)[1]
    notes: list[RoadmapNote] = []
    for block in section.split("\n\n"):
        match = _HEADED_PARAGRAPH.match(block.strip())
        if match is None:
            continue
        body = " ".join(match.group("body").split())
        notes.append(RoadmapNote(heading=match.group("heading").strip(), body=body))
    return tuple(notes)


def entry_for(name: str, module_name: str) -> CatalogueEntry:
    """Read one adapter's declared status and its own roadmap copy."""
    module: ModuleType = importlib.import_module(
        f"revenue_sentinel.integrations.simulated.{module_name}"
    )
    notes = parse_roadmap(module.__doc__)
    return CatalogueEntry(
        name=name,
        module=f"integrations/simulated/{module_name}.py",
        port=f"integrations/ports/{module_name}.py",
        # Read through `status_of`, which raises rather than defaulting -- the same
        # function the MCP server uses to stamp results.
        status=status_of(module),
        summary=_summary(module.__doc__ or ""),
        when_real=notes,
        documented=bool(notes),
    )


def catalogue() -> tuple[CatalogueEntry, ...]:
    """Every adapter, in declaration order."""
    return tuple(entry_for(name, module_name) for name, module_name in ADAPTERS)
