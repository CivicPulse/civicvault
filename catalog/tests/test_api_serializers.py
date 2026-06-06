import dataclasses
import datetime
import json
from decimal import Decimal

from catalog.api.serializers import MeetingSerializer, payload_from_meeting
from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedAppearance,
    ParsedDocument,
    ParsedMeeting,
    ParsedMotion,
    ParsedPerson,
    ParsedVote,
)


def _meeting():
    p = ParsedPerson(full_name="Henry Ficklin", raw_name="Mr. Ficklin", role_hint="President")
    voter = ParsedPerson(full_name="Lisa Garrett-Boyd", raw_name="Ms. Garrett-Boyd")
    item = ParsedAgendaItem(
        order=5,
        code="FSS-3",
        title="Math adoption",
        item_type="action",
        reading_stage="",
        section="V. FISCAL",
        outcome_text="Approved",
        outcome_status="passed",
        amount=Decimal("5515711.09"),
        amount_text="$5,515,711.09",
        motions=(
            ParsedMotion(
                kind="simple",
                sequence=1,
                moved_by=p,
                seconded_by=voter,
                result_text="Approved",
                status="passed",
            ),
        ),
        votes=(ParsedVote(person=voter, value="yea"),),
        file_names=("budget.pdf",),
    )
    doc = ParsedDocument(
        kind="policy",
        title="Budget",
        source_path="/tmp/budget.pdf",
        text="",
        r2_key="BCSD/2025/budget.pdf",
        ocr_status="has_text",
        agenda_item_code="FSS-3",
        is_attachment=True,
    )
    return ParsedMeeting(
        date=datetime.date(2025, 1, 9),
        start_time=datetime.time(19, 0),
        kind_slug="board",
        source_meeting_id="mid-1",
        source_url="https://x",
        source_path="/tmp/m",
        folder_name="2025-01-09 Board",
        title="Board Meeting",
        roster=(p,),
        agenda_items=(item,),
        appearances=(ParsedAppearance(person=p, role="member"),),
        has_minutes=True,
        raw_documents=(doc,),
    )


def test_round_trip_through_json():
    original = _meeting()
    # Simulate the wire: dataclass → JSON string → dict → serializer → dataclass.
    wire = json.loads(json.dumps(payload_from_meeting(original), default=str))
    serializer = MeetingSerializer(data=wire)
    assert serializer.is_valid(), serializer.errors
    rebuilt = serializer.to_ir()
    assert rebuilt == original


def test_decimal_precision_preserved():
    wire = json.loads(json.dumps(payload_from_meeting(_meeting()), default=str))
    rebuilt = MeetingSerializer(data=wire)
    assert rebuilt.is_valid(), rebuilt.errors
    assert rebuilt.to_ir().agenda_items[0].amount == Decimal("5515711.09")


def test_payload_is_plain_data():
    payload = payload_from_meeting(_meeting())
    assert isinstance(payload, dict)
    assert payload["agenda_items"][0]["votes"][0]["value"] == "yea"


def test_blank_agenda_item_code_round_trips():
    doc = ParsedDocument(
        kind="other",
        title="Notice",
        source_path="/n",
        text="",
        agenda_item_code="",
        is_attachment=True,
    )
    m = _meeting()
    m = dataclasses.replace(m, raw_documents=(doc,))
    wire = json.loads(json.dumps(payload_from_meeting(m), default=str))
    s = MeetingSerializer(data=wire)
    assert s.is_valid(), s.errors
    assert s.to_ir().raw_documents[0].agenda_item_code == ""
