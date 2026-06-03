import datetime

import pytest
from django.contrib.postgres.search import SearchQuery, SearchRank

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


@pytest.mark.django_db
def test_search_vector_trigger_populates_on_insert():
    doc = Document.objects.create(title="Lightspeed Renewal", text="chromebooks for students")
    # Title (weight A) is searchable.
    qs = Document.objects.filter(pk=doc.pk)
    assert qs.filter(search_vector=SearchQuery("lightspeed")).exists()
    # Body text (weight B) is searchable.
    assert qs.filter(search_vector=SearchQuery("chromebooks")).exists()


@pytest.mark.django_db
def test_search_vector_trigger_updates_on_text_change():
    doc = Document.objects.create(title="Doc", text="microsoft")
    doc.text = "lenovo lease"
    doc.save()
    qs = Document.objects.filter(pk=doc.pk)
    assert qs.filter(search_vector=SearchQuery("lenovo")).exists()
    assert not qs.filter(search_vector=SearchQuery("microsoft")).exists()


@pytest.mark.django_db
def test_search_vector_weights_title_above_body():
    in_title = Document.objects.create(title="Chromebooks", text="something else entirely")
    in_body = Document.objects.create(title="Unrelated heading", text="chromebooks appear here")
    q = SearchQuery("chromebooks")
    ranked = list(
        Document.objects.filter(search_vector=q)
        .annotate(rank=SearchRank("search_vector", q))
        .order_by("-rank")
        .values_list("pk", flat=True)
    )
    # Title match (weight A) must rank ahead of body-only match (weight B).
    assert ranked.index(in_title.pk) < ranked.index(in_body.pk)
