import datetime

import pytest
from django.db import IntegrityError

from catalog.models import (
    AgendaItem,
    Appearance,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Vote,
)


@pytest.fixture
def meeting(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    return Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )


@pytest.mark.django_db
def test_vote_is_unreviewed_proposal_by_default(meeting):
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")
    person = Person.objects.create(full_name="Myrtice Johnson", slug="myrtice-johnson")
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    assert vote.reviewed is False
    assert vote.value == "yea"


@pytest.mark.django_db
def test_vote_unique_per_person_item(meeting):
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")
    person = Person.objects.create(full_name="P", slug="p")
    Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    with pytest.raises(IntegrityError):
        Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.NAY)


@pytest.mark.django_db
def test_appearance_roles(meeting):
    person = Person.objects.create(full_name="Roy Miller", slug="roy-miller")
    appearance = Appearance.objects.create(
        person=person, meeting=meeting, role=Appearance.Role.SPEAKER
    )
    assert appearance.role == "speaker"
