import datetime

import pytest
from django.db import IntegrityError, transaction

from catalog.models import (
    AgendaItem,
    Appearance,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    Organization,
    Person,
    Vote,
)


@pytest.mark.django_db
def test_document_r2_key_unique_but_blank_allowed():
    Document.objects.create(title="a")  # blank r2_key
    Document.objects.create(title="b")  # blank r2_key again -> allowed
    Document.objects.create(title="c", r2_key="bcsd/x.pdf")
    with pytest.raises(IntegrityError):
        Document.objects.create(title="d", r2_key="bcsd/x.pdf")


@pytest.mark.django_db
def test_media_r2_key_unique_but_blank_allowed():
    MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO)
    MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO)  # blank again -> allowed
    MediaAsset.objects.create(kind=MediaAsset.Kind.PDF, r2_key="bcsd/v.mp4")
    with pytest.raises(IntegrityError):
        MediaAsset.objects.create(kind=MediaAsset.Kind.PDF, r2_key="bcsd/v.mp4")


@pytest.mark.django_db
def test_confidence_range_enforced_on_person():
    with pytest.raises(IntegrityError):
        Person.objects.create(full_name="x", slug="x", confidence=2.0)


@pytest.mark.django_db
def test_confidence_range_enforced_on_vote():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="x")
    person = Person.objects.create(full_name="p", slug="p")
    with pytest.raises(IntegrityError):
        Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA, confidence=-0.1)


@pytest.mark.django_db
def test_meeting_slug_unique_within_jurisdiction():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 4, 17),
        kind=Meeting.Kind.BOARD,
        slug="2025-04-17-board",
        source_meeting_id="1",
    )
    with pytest.raises(IntegrityError):
        Meeting.objects.create(
            body=body,
            jurisdiction=jur,
            date=datetime.date(2025, 4, 18),
            kind=Meeting.Kind.BOARD,
            slug="2025-04-17-board",
            source_meeting_id="2",
        )


@pytest.mark.django_db
def test_agenda_item_order_unique_per_meeting():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    AgendaItem.objects.create(meeting=meeting, order=1, title="x")
    with pytest.raises(IntegrityError):
        AgendaItem.objects.create(meeting=meeting, order=1, title="y")


@pytest.mark.django_db
def test_appearance_unique_per_person_meeting_role():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b"
    )
    person = Person.objects.create(full_name="p", slug="p")
    Appearance.objects.create(person=person, meeting=meeting, role=Appearance.Role.MEMBER)
    # same person, same meeting, different role -> allowed (member + invocation)
    Appearance.objects.create(person=person, meeting=meeting, role=Appearance.Role.INVOCATION)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Appearance.objects.create(person=person, meeting=meeting, role=Appearance.Role.MEMBER)
