import dataclasses
import datetime

import pytest
from django.contrib.postgres.search import SearchQuery

from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedAppearance,
    ParsedDocument,
    ParsedMeeting,
    ParsedMotion,
    ParsedPerson,
    ParsedRecording,
    ParsedTranscriptSegment,
    ParsedVote,
)
from catalog.ingest.loader import load_meeting, load_recording
from catalog.ingest.match import CoverageDecision
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Motion,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
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
    # Citations are wiped+recreated on reload, so the count stays stable at 8
    # (3 roster + 1 invocation + 2 motions + 2 votes).
    assert Citation.objects.count() == 8


@pytest.mark.django_db
def test_duplicate_roster_entry_raises_valueerror_not_integrityerror(context):
    """Two roster entries that slugify to the same slug must raise a descriptive
    ValueError (not a raw IntegrityError) and must NOT partially persist the meeting."""
    jur, source, body = context
    # "John Smith" and "John  Smith" (extra space) both slugify to "john-smith".
    # The second roster entry will attempt to create a duplicate Appearance for the
    # already-seen Person, triggering the UniqueConstraint(person, meeting, role).
    john_a = _person("John Smith")
    john_b = ParsedPerson(full_name="John Smith", raw_name="John  Smith")  # same slug
    duplicate_roster_meeting = ParsedMeeting(
        date=datetime.date(2025, 1, 1),
        start_time=datetime.time(10, 0),
        kind_slug="committee-meeting",
        source_meeting_id="999001",
        source_url="https://example.com/999001",
        source_path="/x/dupe-roster",
        folder_name="2025-01-01_1000_committee-meeting_mid-999001",
        title="Duplicate Roster Test",
        roster=(john_a, john_b),
        agenda_items=(),
        appearances=(),
        has_minutes=False,
        raw_documents=(),
    )

    with pytest.raises(ValueError, match="Duplicate member appearance"):
        load_meeting(duplicate_roster_meeting, source=source, jurisdiction=jur, body=body)

    # The transaction must have been fully rolled back — no meeting persisted.
    assert Meeting.objects.filter(source_meeting_id="999001").count() == 0


@pytest.mark.django_db
def test_duplicate_vote_raises_valueerror_not_integrityerror(context):
    """Two votes by the same person on the same agenda item must raise a descriptive
    ValueError (not a raw IntegrityError) and must NOT partially persist the meeting."""
    jur, source, body = context
    voter = _person("Jane Doe")
    item_with_duplicate_votes = ParsedAgendaItem(
        order=1,
        code="DUP-1",
        title="Duplicate vote item",
        item_type="action",
        reading_stage="",
        section="I. TEST",
        outcome_text="approved",
        outcome_status="passed",
        motions=(),
        votes=(
            ParsedVote(person=voter, value="yea"),
            ParsedVote(person=voter, value="yea"),  # same person, same item
        ),
    )
    duplicate_vote_meeting = ParsedMeeting(
        date=datetime.date(2025, 1, 2),
        start_time=datetime.time(10, 0),
        kind_slug="committee-meeting",
        source_meeting_id="999002",
        source_url="https://example.com/999002",
        source_path="/x/dupe-vote",
        folder_name="2025-01-02_1000_committee-meeting_mid-999002",
        title="Duplicate Vote Test",
        roster=(),
        agenda_items=(item_with_duplicate_votes,),
        appearances=(),
        has_minutes=False,
        raw_documents=(),
    )

    with pytest.raises(ValueError, match="Duplicate vote"):
        load_meeting(duplicate_vote_meeting, source=source, jurisdiction=jur, body=body)

    # The transaction must have been fully rolled back — no meeting persisted.
    assert Meeting.objects.filter(source_meeting_id="999002").count() == 0


@pytest.mark.django_db
def test_loader_persists_attachment_documents(context):
    jur, source, body = context
    base = _sample_meeting()  # has agenda item FSS-3 + a minutes source doc
    parsed = dataclasses.replace(
        base,
        raw_documents=base.raw_documents
        + (
            ParsedDocument(
                kind="memo",
                title="HMH",
                source_path="/x/files/hmh.pdf",
                text="chromebooks",
                r2_key="BCSD/x/files/hmh.pdf",
                ocr_status="has_text",
                agenda_item_code="FSS-3",
                is_attachment=True,
            ),
            ParsedDocument(
                kind="other",
                title="Extra",
                source_path="/x/files/extra.pdf",
                text="",
                r2_key="BCSD/x/files/extra.pdf",
                ocr_status="ocr_needed",
                agenda_item_code=None,
                is_attachment=True,
            ),
        ),
    )
    meeting = load_meeting(parsed, source=source, jurisdiction=jur, body=body)

    docs = Document.objects.filter(meeting=meeting, r2_key__startswith="BCSD/")
    assert docs.count() == 2
    hmh = docs.get(r2_key="BCSD/x/files/hmh.pdf")
    assert hmh.kind == Document.Kind.MEMO
    assert hmh.ocr_status == Document.OCRStatus.HAS_TEXT
    assert hmh.agenda_item.code == "FSS-3"
    extra = docs.get(r2_key="BCSD/x/files/extra.pdf")
    assert extra.agenda_item is None  # meeting-level
    assert extra.ocr_status == Document.OCRStatus.OCR_NEEDED


@pytest.mark.django_db
def test_loader_attachment_documents_are_idempotent(context):
    jur, source, body = context
    base = _sample_meeting()
    parsed = dataclasses.replace(
        base,
        raw_documents=base.raw_documents
        + (
            ParsedDocument(
                kind="memo",
                title="HMH",
                source_path="/x/files/hmh.pdf",
                text="chromebooks",
                r2_key="BCSD/x/files/hmh.pdf",
                ocr_status="has_text",
                agenda_item_code="FSS-3",
                is_attachment=True,
            ),
        ),
    )
    load_meeting(parsed, source=source, jurisdiction=jur, body=body)
    meeting = load_meeting(parsed, source=source, jurisdiction=jur, body=body)  # re-ingest
    assert Document.objects.filter(meeting=meeting, r2_key="BCSD/x/files/hmh.pdf").count() == 1


_DEFAULT_SEGMENTS = (ParsedTranscriptSegment(0.0, 2.0, "call to order"),)


def _recording(youtube_id="vid1", segments=_DEFAULT_SEGMENTS):
    return ParsedRecording(
        youtube_id=youtube_id,
        title="Committee and Board Meeting 1/19/2023",
        recorded_on=datetime.date(2023, 1, 19),
        upload_date=datetime.date(2023, 1, 20),
        duration_seconds=120,
        source_url=f"https://youtu.be/{youtube_id}",
        r2_key="",
        is_combined=True,
        segments=segments,
        transcript_origin="youtube_captions",
    )


@pytest.mark.django_db
def test_load_recording_creates_asset_transcript_segments(context):
    _, source, _ = context
    media = load_recording(_recording(), [], source=source)
    assert media.youtube_id == "vid1"
    assert media.kind == MediaAsset.Kind.VIDEO
    assert media.recorded_on.isoformat() == "2023-01-19"
    assert media.transcripts.count() == 1
    assert media.transcripts.first().origin == Transcript.Origin.YOUTUBE_CAPTIONS
    assert TranscriptSegment.objects.filter(transcript__media=media).count() == 1


@pytest.mark.django_db
def test_load_recording_populates_segment_fts(context):
    _, source, _ = context
    media = load_recording(
        _recording(segments=(ParsedTranscriptSegment(0.0, 2.0, "chromebooks approved"),)),
        [],
        source=source,
    )
    seg_qs = TranscriptSegment.objects.filter(transcript__media=media)
    assert seg_qs.filter(search_vector=SearchQuery("chromebooks")).exists()


@pytest.mark.django_db
def test_load_recording_creates_coverage_rows(context):
    jur, source, body = context
    committee = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        source=source,
        source_meeting_id="107503",
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(16, 0),
        kind=Meeting.Kind.COMMITTEE,
        slug="c-107503",
    )
    board = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        source=source,
        source_meeting_id="107593",
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(18, 30),
        kind=Meeting.Kind.BOARD,
        slug="b-107593",
    )
    decisions = [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=90.0),
        CoverageDecision(meeting_id=board.pk, start_offset=90.0, end_offset=None),
    ]
    media = load_recording(_recording(), decisions, source=source)
    covs = MeetingCoverage.objects.filter(media=media).order_by("start_offset")
    assert covs.count() == 2
    assert covs[0].meeting == committee
    assert covs[0].start_offset == 0.0 and covs[0].end_offset == 90.0
    assert covs[1].meeting == board and covs[1].end_offset is None
    assert all(c.split_confirmed is False for c in covs)


@pytest.mark.django_db
def test_load_recording_is_idempotent(context):
    _, source, _ = context
    load_recording(_recording(), [], source=source)
    media = load_recording(_recording(), [], source=source)  # re-ingest
    assert MediaAsset.objects.filter(youtube_id="vid1").count() == 1
    assert media.transcripts.count() == 1
    assert TranscriptSegment.objects.filter(transcript__media=media).count() == 1


@pytest.mark.django_db
def test_load_recording_without_segments_creates_no_transcript(context):
    _, source, _ = context
    rec = dataclasses.replace(_recording(), segments=(), transcript_origin="")
    media = load_recording(rec, [], source=source)
    assert media.transcripts.count() == 0


@pytest.mark.django_db
def test_load_recording_unresolvable_meeting_raises(context):
    _, source, _ = context
    decisions = [CoverageDecision(meeting_id=999999, start_offset=0.0, end_offset=None)]
    with pytest.raises(ValueError, match="no Meeting"):
        load_recording(_recording(), decisions, source=source)


@pytest.mark.django_db
def test_load_recording_requires_youtube_id(context):
    _, source, _ = context
    rec = dataclasses.replace(_recording(), youtube_id="")
    with pytest.raises(ValueError, match="non-empty youtube_id"):
        load_recording(rec, [], source=source)
