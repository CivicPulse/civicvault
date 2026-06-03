import dataclasses
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


def test_parsed_person_is_frozen():
    p = ParsedPerson(full_name="Myrtice Johnson", raw_name="Ms. Myrtice Johnson")
    assert p.full_name == "Myrtice Johnson"
    try:
        p.full_name = "x"
        raise AssertionError("should be frozen")
    except dataclasses.FrozenInstanceError:
        pass


def test_parsed_meeting_composes_children():
    person = ParsedPerson(full_name="James Freeman", raw_name="Mr. James Freeman")
    motion = ParsedMotion(
        kind="simple",
        sequence=0,
        moved_by=person,
        seconded_by=None,
        result_text="Unanimously approved",
        status="unanimous",
    )
    vote = ParsedVote(person=person, value="yea")
    item = ParsedAgendaItem(
        order=5,
        code="FSS-3",
        title="Math adoption",
        item_type="action",
        reading_stage="",
        section="V. FISCAL/SUPPORT SERVICES COMMITTEE",
        outcome_text="authorized ... $5,515,711.09",
        outcome_status="unanimous",
        motions=(motion,),
        votes=(vote,),
        file_names=("hmh.pdf",),
    )
    appearance = ParsedAppearance(person=person, role="invocation")
    doc = ParsedDocument(kind="minutes", title="minutes.md", source_path="x/minutes.md", text="...")
    meeting = ParsedMeeting(
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(16, 0),
        kind_slug="committee-meeting",
        source_meeting_id="124789",
        source_url="https://...",
        source_path="x",
        folder_name="2025-04-17_1600_committee-meeting_mid-124789",
        title="Committee Meeting",
        roster=(person,),
        agenda_items=(item,),
        appearances=(appearance,),
        has_minutes=True,
        raw_documents=(doc,),
    )
    assert meeting.agenda_items[0].motions[0].moved_by.full_name == "James Freeman"
    assert meeting.has_minutes is True


def test_parsed_document_attachment_fields_default():
    from catalog.ingest.ir import ParsedDocument

    # Existing source-doc usage keeps working with the new fields defaulted.
    src = ParsedDocument(kind="minutes", title="minutes.md", source_path="/x/minutes.md", text="hi")
    assert src.r2_key == ""
    assert src.ocr_status == "unknown"
    assert src.agenda_item_code is None
    assert src.is_attachment is False

    att = ParsedDocument(
        kind="memo",
        title="Action Memo",
        source_path="/x/files/m.pdf",
        text="body",
        r2_key="BCSD/.../files/m.pdf",
        ocr_status="has_text",
        agenda_item_code="FSS-3",
        is_attachment=True,
    )
    assert att.is_attachment is True
    assert att.agenda_item_code == "FSS-3"


def test_parsed_transcript_segment_is_frozen():
    from catalog.ingest.ir import ParsedTranscriptSegment

    seg = ParsedTranscriptSegment(start=1.5, end=3.0, text="hello")
    assert seg.start == 1.5 and seg.end == 3.0 and seg.text == "hello"
    with pytest.raises(dataclasses.FrozenInstanceError):
        seg.text = "x"


def test_parsed_recording_defaults():
    import datetime

    from catalog.ingest.ir import ParsedRecording, ParsedTranscriptSegment

    rec = ParsedRecording(
        youtube_id="CWjfBn10EJc",
        title="Committee and Board Meeting 1/19/2023",
        recorded_on=datetime.date(2023, 1, 19),
        upload_date=datetime.date(2023, 1, 20),
        duration_seconds=13486,
        source_url="https://www.youtube.com/watch?v=CWjfBn10EJc",
        r2_key="",
        is_combined=True,
    )
    assert rec.segments == ()
    assert rec.transcript_origin == "youtube_captions"
    assert rec.source_path == ""
    # segments accept ParsedTranscriptSegment tuples
    rec2 = dataclasses.replace(rec, segments=(ParsedTranscriptSegment(0.0, 1.0, "x"),))
    assert rec2.segments[0].text == "x"
