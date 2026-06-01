from catalog.ingest.bcsd.agenda_md import parse_agenda_md
from catalog.tests.fixtures import fixture_text


def test_agenda_items_from_outline():
    items = parse_agenda_md(fixture_text("committee", "agenda.md"))
    by_code = {it.code: it for it in items if it.code}
    assert "FSS-3" in by_code
    assert by_code["FSS-3"].item_type == "action"
    assert "FISCAL" in by_code["FSS-3"].section.upper()


def test_agenda_has_no_outcomes():
    items = parse_agenda_md(fixture_text("committee", "agenda.md"))
    assert all(it.order > 0 for it in items)
