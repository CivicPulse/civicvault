import datetime

import pytest

from catalog.models import (
    AgendaItem,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
)


@pytest.mark.django_db
def test_document_links_meeting_and_agenda_item():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.COMMITTEE, slug="c"
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Contract award")
    doc = Document.objects.create(
        title="WM2A Architects proposal",
        kind=Document.Kind.PRESENTATION,
        meeting=meeting,
        agenda_item=item,
        text="full extracted text here",
        ocr_status=Document.OCRStatus.HAS_TEXT,
    )
    assert doc.meeting == meeting
    assert doc.agenda_item == item
    assert doc.access_level == Document.AccessLevel.PUBLIC  # default
    assert doc.og_metadata == {}  # JSON default


@pytest.mark.django_db
def test_standalone_document_has_no_meeting():
    doc = Document.objects.create(
        title="ACFR FY2024", kind=Document.Kind.REPORT, text="balance sheet"
    )
    assert doc.meeting is None
