import datetime

import pytest
from django.db import IntegrityError

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Vote,
)


@pytest.fixture
def fixtures(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")
    person = Person.objects.create(full_name="Myrtice Johnson", slug="mj")
    minutes = Document.objects.create(
        title="minutes.md", kind=Document.Kind.MINUTES, meeting=meeting
    )
    return meeting, item, person, minutes


@pytest.mark.django_db
def test_citation_attaches_a_fact_to_a_document(fixtures):
    _meeting, item, person, minutes = fixtures
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    cite = Citation.objects.create(
        fact=vote, document=minutes, page=3, quote="Voting results: Unanimously approved"
    )
    assert cite.fact == vote
    # for_fact() retrieves every citation backing a given fact.
    assert list(Citation.objects.for_fact(vote)) == [cite]


@pytest.mark.django_db
def test_citation_works_across_fact_types(fixtures):
    meeting, _item, person, minutes = fixtures
    appearance = Appearance.objects.create(
        person=person, meeting=meeting, role=Appearance.Role.MEMBER
    )
    Citation.objects.create(fact=appearance, document=minutes)
    assert Citation.objects.for_fact(appearance).count() == 1


@pytest.mark.django_db
def test_citation_requires_some_evidence(fixtures):
    """A citation with neither a document nor a transcript segment is rejected."""
    meeting, item, person, _minutes = fixtures
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    with pytest.raises(IntegrityError):
        Citation.objects.create(fact=vote, document=None, transcript_segment=None)
