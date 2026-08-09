"""The integration catalogue reads the adapters; it does not describe them.

The distinction these tests defend: a catalogue that restates what the adapters do can
drift away from them silently, and the drift shows up as a dashboard confidently
displaying something false. So the tests below check *provenance* -- that the status and
the roadmap copy are the adapter's own -- rather than checking the wording.
"""

from __future__ import annotations

import pytest

from revenue_sentinel.integrations import catalogue as cat
from revenue_sentinel.integrations.simulated import crm, messaging
from revenue_sentinel.integrations.status import SIMULATED


def test_every_adapter_is_in_the_catalogue() -> None:
    entries = cat.catalogue()
    assert len(entries) == 6
    assert {entry.name for entry in entries} == {
        "CRM",
        "Product usage",
        "Engagement",
        "Support",
        "Enrichment",
        "Messaging",
    }


def test_every_adapter_reports_simulated_in_v1() -> None:
    """Rule 5. If this ever fails, something claims to be real -- check before shipping."""
    assert all(entry.status == SIMULATED for entry in cat.catalogue())


def test_status_is_the_adapter_module_attribute_not_a_catalogue_constant() -> None:
    """Read through to the module, so the two cannot disagree."""
    entry = cat.entry_for("CRM", "crm")
    assert entry.status == crm.INTEGRATION_STATUS


def test_a_changed_adapter_status_changes_the_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    """The catalogue is derived, and this proves it by moving the source.

    A hand-maintained list would keep saying SIMULATED here, which is precisely the
    failure that would matter most.
    """
    monkeypatch.setattr(crm, "INTEGRATION_STATUS", "IMPLEMENTED")

    entry = cat.entry_for("CRM", "crm")

    assert entry.status == "IMPLEMENTED"


def test_roadmap_copy_comes_from_the_adapter_docstring() -> None:
    entry = cat.entry_for("CRM", "crm")

    assert entry.documented
    headings = [note.heading for note in entry.when_real]
    assert headings == ["API", "Auth", "Rate limits", "Pagination", "Fields that differ", "Writes"]
    # Not paraphrased: the body is the adapter's own sentence.
    api_note = next(note for note in entry.when_real if note.heading == "API")
    assert "HubSpot CRM v3" in api_note.body
    assert api_note.body in " ".join((crm.__doc__ or "").split())


def test_every_adapter_documents_what_changes_when_it_becomes_real() -> None:
    """The section is a commitment, not a nicety -- so its absence is a test failure.

    This is what makes the `documented=False` fallback safe: it can only be reached by
    running under `python -O`, never by someone deleting the section.
    """
    for entry in cat.catalogue():
        assert entry.documented, f"{entry.module} has no roadmap section"
        assert len(entry.when_real) >= 4


def test_roadmap_parsing_ignores_present_tense_text_before_the_section() -> None:
    """`messaging.py` states "there is no send method" *before* the roadmap heading.

    Filing that under "what changes when this becomes real" would turn a present-tense
    guarantee into a future one -- exactly backwards.
    """
    entry = cat.entry_for("Messaging", "messaging")

    headings = [note.heading for note in entry.when_real]
    assert "There is no send method, here or in the port" not in headings
    assert headings[0] == "API"
    assert "no send method" in (messaging.__doc__ or "")


def test_a_stripped_docstring_reports_undocumented_rather_than_inventing_copy() -> None:
    """`python -O` removes docstrings. The honest answer is "not documented"."""
    assert cat.parse_roadmap(None) == ()
    assert cat.parse_roadmap("A docstring with no roadmap section.") == ()


def test_summary_is_the_adapters_own_first_line() -> None:
    entry = cat.entry_for("Support", "support")
    assert entry.summary == "Support adapter -- SIMULATED."
