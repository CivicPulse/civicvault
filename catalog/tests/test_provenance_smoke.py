import datetime

import pytest

from catalog.models import (
    AgendaItem,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Source,
    Vote,
)


@pytest.mark.django_db
def test_full_provenance_chain():
    jur = Jurisdiction.objects.create(
        name="Bibb County Board of Education",
        slug="bibb-county-boe",
        kind=Jurisdiction.Kind.SCHOOL_DISTRICT,
    )
    src = Source.objects.create(name="BCSD BOE Meetings", slug="bcsd-boe-meetings", adapter="bcsd")
    body = Organization.objects.create(
        name="Board of Education", slug="boe", kind=Organization.Kind.COMMITTEE, jurisdiction=jur
    )
    meeting = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        source=src,
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(18, 30),
        kind=Meeting.kind_from_slug("board-meeting"),
        raw_type_slug="board-meeting",
        source_meeting_id="124791",
        slug="2025-04-17-board-mid-124791",
    )
    item = AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        code="FI-1",
        title="Adopt FY2026 budget",
        item_type=AgendaItem.ItemType.ACTION,
        outcome_status=AgendaItem.OutcomeStatus.PASSED,
    )
    minutes = Document.objects.create(
        title="minutes.md",
        kind=Document.Kind.MINUTES,
        meeting=meeting,
        source=src,
        ocr_status=Document.OCRStatus.HAS_TEXT,
    )
    person = Person.objects.create(full_name="Myrtice Johnson", slug="myrtice-johnson")
    vote = Vote.objects.create(person=person, agenda_item=item, value=Vote.Value.YEA)
    Citation.objects.create(fact=vote, document=minutes, page=4, quote="Yes: Ms. Myrtice Johnson")

    # The vote is reachable from the meeting, and is backed by a citation.
    assert meeting.kind == Meeting.Kind.BOARD
    assert person.votes.get().agenda_item.meeting == meeting
    citations = Citation.objects.for_fact(vote)
    assert citations.count() == 1
    assert citations.first().document.meeting == meeting
    # Ingested facts start unreviewed (hidden from public until admin confirms).
    assert vote.reviewed is False
