import datetime

import pytest

from catalog.models import AgendaItem, Jurisdiction, Meeting, Organization


def test_kind_from_slug_maps_known_and_defaults_unknown():
    assert Meeting.kind_from_slug("committee-meeting") == Meeting.Kind.COMMITTEE
    assert Meeting.kind_from_slug("board-meeting") == Meeting.Kind.BOARD
    assert Meeting.kind_from_slug("called-board-meeting") == Meeting.Kind.CALLED_BOARD
    assert Meeting.kind_from_slug("totally-unknown-slug") == Meeting.Kind.OTHER


@pytest.mark.django_db
def test_meeting_with_agenda_item():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(
        name="Board of Education", slug="boe", kind=Organization.Kind.COMMITTEE, jurisdiction=jur
    )
    meeting = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(16, 0),
        kind=Meeting.kind_from_slug("committee-meeting"),
        raw_type_slug="committee-meeting",
        source_meeting_id="124789",
        slug="2025-04-17-committee-mid-124789",
    )
    item = AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        code="FSS-3",
        title="Award of contract",
        item_type=AgendaItem.ItemType.ACTION,
        outcome_status=AgendaItem.OutcomeStatus.UNANIMOUS,
    )
    assert meeting.kind == Meeting.Kind.COMMITTEE
    assert item.meeting == meeting
    assert str(item) == "FSS-3 Award of contract"
