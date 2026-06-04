"""AgendaItem carries an optional structured contract amount + verbatim phrase."""

from decimal import Decimal

import pytest

from catalog.models import AgendaItem, Jurisdiction, Meeting, Organization


@pytest.mark.django_db
def test_agendaitem_stores_amount_and_phrase():
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE
    )
    meeting = Meeting.objects.create(body=body, jurisdiction=jur, date="2025-05-15", slug="m1")
    item = AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        title="Renewal of Amira Learning",
        amount=Decimal("255300.00"),
        amount_text="in an amount not to exceed $255,300.00",
    )
    item.refresh_from_db()
    assert item.amount == Decimal("255300.00")
    assert item.amount_text == "in an amount not to exceed $255,300.00"


@pytest.mark.django_db
def test_agendaitem_amount_defaults_to_null():
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE
    )
    meeting = Meeting.objects.create(body=body, jurisdiction=jur, date="2025-05-15", slug="m1")
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Policy Review")
    item.refresh_from_db()
    assert item.amount is None
    assert item.amount_text == ""
