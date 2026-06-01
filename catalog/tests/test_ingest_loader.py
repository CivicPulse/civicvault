import datetime

import pytest

from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedAppearance,
    ParsedDocument,
    ParsedMeeting,
    ParsedMotion,
    ParsedPerson,
    ParsedVote,
)
from catalog.ingest.loader import load_meeting
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Person,
    Source,
    Vote,
)


@pytest.fixture
def context(db):
    jur = Jurisdiction.objects.create(
        name="Bibb County Board of Education",
        slug="bibb-county-boe",
        kind=Jurisdiction.Kind.SCHOOL_DISTRICT,
    )
    source = Source.objects.create(
        name="BCSD BOE Meetings", slug="bcsd-boe-meetings", adapter="bcsd"
    )
    body = Organization.objects.create(
        name="Board of Education", slug="boe", kind=Organization.Kind.COMMITTEE, jurisdiction=jur
    )
    return jur, source, body


def _person(name):
    return ParsedPerson(full_name=name, raw_name=name)


def _sample_meeting():
    ficklin = _person("Henry Ficklin")
    boyd = _person("Lisa Garrett-Boyd")
    johnson = _person("Myrtice Johnson")
    fss3 = ParsedAgendaItem(
        order=5,
        code="FSS-3",
        title="Math adoption",
        item_type="action",
        reading_stage="",
        section="V. FISCAL",
        outcome_text="authorized ... $5,515,711.09",
        outcome_status="unanimous",
        motions=(
            ParsedMotion(
                kind="simple",
                sequence=0,
                moved_by=ficklin,
                seconded_by=boyd,
                result_text="Unanimously approved",
                status="unanimous",
            ),
        ),
    )
    consent = ParsedAgendaItem(
        order=20,
        code="",
        title="Confirmation of Minutes",
        item_type="action",
        reading_stage="",
        section="VIII. CONSENT AGENDA",
        outcome_text="approved consent",
        outcome_status="passed",
        motions=(
            ParsedMotion(
                kind="simple",
                sequence=0,
                moved_by=johnson,
                seconded_by=ficklin,
                result_text="Unanimously approved",
                status="unanimous",
            ),
        ),
        votes=(ParsedVote(person=johnson, value="yea"), ParsedVote(person=ficklin, value="yea")),
    )
    return ParsedMeeting(
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(16, 0),
        kind_slug="committee-meeting",
        source_meeting_id="124789",
        source_url="https://simbli/MID=124789",
        source_path="/x/committee",
        folder_name="2025-04-17_1600_committee-meeting_mid-124789",
        title="Committee Meeting",
        roster=(johnson, ficklin, boyd),
        agenda_items=(fss3, consent),
        appearances=(ParsedAppearance(person=ficklin, role="invocation"),),
        has_minutes=True,
        raw_documents=(
            ParsedDocument(
                kind="minutes",
                title="minutes.md",
                source_path="/x/committee/minutes.md",
                text="...",
            ),
        ),
    )


@pytest.mark.django_db
def test_load_creates_meeting_items_and_proposals(context):
    jur, source, body = context
    meeting = load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)

    assert meeting.source_meeting_id == "124789"
    assert meeting.kind == Meeting.Kind.COMMITTEE
    assert meeting.start_time == datetime.time(16, 0)
    assert Appearance.objects.filter(meeting=meeting, role=Appearance.Role.MEMBER).count() == 3
    assert Appearance.objects.filter(meeting=meeting, role=Appearance.Role.INVOCATION).count() == 1
    fss3 = AgendaItem.objects.get(meeting=meeting, code="FSS-3")
    assert fss3.outcome_status == AgendaItem.OutcomeStatus.UNANIMOUS
    assert Vote.objects.filter(agenda_item=fss3).count() == 0
    assert Motion.objects.filter(agenda_item=fss3).count() == 1
    consent = AgendaItem.objects.get(meeting=meeting, title="Confirmation of Minutes")
    assert Vote.objects.filter(agenda_item=consent).count() == 2


@pytest.mark.django_db
def test_every_fact_has_a_citation_into_minutes(context):
    jur, source, body = context
    meeting = load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    minutes = Document.objects.get(meeting=meeting, kind=Document.Kind.MINUTES)

    for vote in Vote.objects.filter(agenda_item__meeting=meeting):
        cites = Citation.objects.for_fact(vote)
        assert cites.count() >= 1
        assert cites.first().document == minutes
    for motion in Motion.objects.filter(agenda_item__meeting=meeting):
        assert Citation.objects.for_fact(motion).count() >= 1
    for appearance in Appearance.objects.filter(meeting=meeting):
        assert Citation.objects.for_fact(appearance).count() >= 1


@pytest.mark.django_db
def test_everything_is_unreviewed(context):
    jur, source, body = context
    meeting = load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    assert not Vote.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
    assert not Appearance.objects.filter(meeting=meeting, reviewed=True).exists()
    assert not Motion.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
    assert not Person.objects.filter(reviewed=True).exists()


@pytest.mark.django_db
def test_reload_is_idempotent(context):
    jur, source, body = context
    load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    load_meeting(_sample_meeting(), source=source, jurisdiction=jur, body=body)
    assert Meeting.objects.filter(source=source, source_meeting_id="124789").count() == 1
    meeting = Meeting.objects.get(source=source, source_meeting_id="124789")
    assert AgendaItem.objects.filter(meeting=meeting).count() == 2
    assert Vote.objects.filter(agenda_item__meeting=meeting).count() == 2
    assert Person.objects.count() == 3
