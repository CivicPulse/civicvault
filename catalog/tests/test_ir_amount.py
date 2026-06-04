"""ParsedAgendaItem carries an optional Decimal amount + verbatim phrase."""

from decimal import Decimal

from catalog.ingest.ir import ParsedAgendaItem


def test_parsed_agenda_item_defaults_have_no_amount():
    item = ParsedAgendaItem(
        order=1, code="FSS-3", title="x", item_type="action", reading_stage="", section="S"
    )
    assert item.amount is None
    assert item.amount_text == ""


def test_parsed_agenda_item_accepts_amount():
    item = ParsedAgendaItem(
        order=1,
        code="FSS-3",
        title="x",
        item_type="action",
        reading_stage="",
        section="S",
        amount=Decimal("255300.00"),
        amount_text="in an amount not to exceed $255,300.00",
    )
    assert item.amount == Decimal("255300.00")
    assert item.amount_text == "in an amount not to exceed $255,300.00"
