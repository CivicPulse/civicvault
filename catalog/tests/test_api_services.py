import datetime

import pytest

from catalog.api.services import bcsd_context, meeting_has_reviewed_facts
from catalog.models import AgendaItem, Appearance, Meeting, Motion, Person, Vote


@pytest.mark.django_db
def test_bcsd_context_is_idempotent():
    jur1, src1, body1 = bcsd_context()
    jur2, src2, body2 = bcsd_context()
    assert (jur1.pk, src1.pk, body1.pk) == (jur2.pk, src2.pk, body2.pk)
    assert src1.slug == "bcsd-boe-meetings"


@pytest.mark.django_db
def test_guard_false_for_unknown_meeting():
    _, source, _ = bcsd_context()
    assert meeting_has_reviewed_facts(source, "mid-404") is False


@pytest.mark.django_db
def test_guard_detects_reviewed_vote():
    jur, source, body = bcsd_context()
    meeting = Meeting.objects.create(
        source=source,
        jurisdiction=jur,
        body=body,
        source_meeting_id="mid-1",
        date=datetime.date(2025, 1, 9),
        kind=Meeting.Kind.BOARD,
        slug="m-1",
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, code="A", title="x")
    person = Person.objects.create(full_name="Jane Doe", slug="jane-doe")
    assert meeting_has_reviewed_facts(source, "mid-1") is False
    Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA, reviewed=True)
    assert meeting_has_reviewed_facts(source, "mid-1") is True


@pytest.mark.django_db
def test_guard_detects_reviewed_appearance():
    jur, source, body = bcsd_context()
    meeting = Meeting.objects.create(
        source=source,
        jurisdiction=jur,
        body=body,
        source_meeting_id="mid-2",
        date=datetime.date(2025, 1, 9),
        kind=Meeting.Kind.BOARD,
        slug="m-2",
    )
    person = Person.objects.create(full_name="Pat Roe", slug="pat-roe")
    assert meeting_has_reviewed_facts(source, "mid-2") is False
    Appearance.objects.create(
        person=person, meeting=meeting, role=Appearance.Role.MEMBER, reviewed=True
    )
    assert meeting_has_reviewed_facts(source, "mid-2") is True


@pytest.mark.django_db
def test_guard_detects_reviewed_motion():
    jur, source, body = bcsd_context()
    meeting = Meeting.objects.create(
        source=source,
        jurisdiction=jur,
        body=body,
        source_meeting_id="mid-3",
        date=datetime.date(2025, 1, 9),
        kind=Meeting.Kind.BOARD,
        slug="m-3",
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, code="B", title="y")
    assert meeting_has_reviewed_facts(source, "mid-3") is False
    Motion.objects.create(
        agenda_item=item,
        kind=Motion.Kind.SIMPLE,
        sequence=1,
        result_text="",
        status=Motion.Status.NONE,
        reviewed=True,
    )
    assert meeting_has_reviewed_facts(source, "mid-3") is True
