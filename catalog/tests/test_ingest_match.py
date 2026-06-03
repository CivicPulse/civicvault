import datetime

import pytest

from catalog.ingest.ir import ParsedRecording, ParsedTranscriptSegment
from catalog.ingest.match import CoverageDecision, match_recording, suggest_split
from catalog.models import Jurisdiction, Meeting, Organization


def _seg(start, text):
    return ParsedTranscriptSegment(start=start, end=start + 1, text=text)


def _recording(is_combined, segments=()):
    return ParsedRecording(
        youtube_id="vid",
        title="Committee and Board Meeting 1/19/2023",
        recorded_on=datetime.date(2023, 1, 19),
        upload_date=datetime.date(2023, 1, 20),
        duration_seconds=120,
        source_url="https://youtu.be/vid",
        r2_key="",
        is_combined=is_combined,
        segments=segments,
    )


def test_suggest_split_returns_second_to_order():
    segs = (
        _seg(5.0, "committee meeting call to order"),
        _seg(50.0, "some business"),
        _seg(90.0, "we now come to order"),
    )
    assert suggest_split(segs) == 90.0


def test_suggest_split_none_when_fewer_than_two_markers():
    assert suggest_split((_seg(5.0, "call to order"),)) is None
    assert suggest_split(()) is None


@pytest.fixture
def two_meetings(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    committee = Meeting.objects.create(
        body=body,
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(16, 0),
        kind=Meeting.Kind.COMMITTEE,
        slug="c-107503",
    )
    board = Meeting.objects.create(
        body=body,
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(18, 30),
        kind=Meeting.Kind.BOARD,
        slug="b-107593",
    )
    return committee, board


@pytest.mark.django_db
def test_combined_two_meetings_yields_two_windows_with_split(two_meetings):
    committee, board = two_meetings
    rec = _recording(
        is_combined=True,
        segments=(_seg(5.0, "call to order"), _seg(90.0, "come to order")),
    )
    decisions = match_recording(rec, [board, committee])  # order shouldn't matter

    assert decisions == [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=90.0),
        CoverageDecision(meeting_id=board.pk, start_offset=90.0, end_offset=None),
    ]
    assert all(d.split_confirmed is False for d in decisions)


@pytest.mark.django_db
def test_combined_without_split_markers_is_single_window_on_committee(two_meetings):
    committee, board = two_meetings
    rec = _recording(is_combined=True, segments=(_seg(5.0, "no markers here"),))
    decisions = match_recording(rec, [committee, board])
    assert decisions == [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=None)
    ]


@pytest.mark.django_db
def test_single_meeting_one_full_window(two_meetings):
    committee, _ = two_meetings
    rec = _recording(is_combined=False)
    decisions = match_recording(rec, [committee])
    assert decisions == [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=None)
    ]


def test_no_candidate_meetings_is_unlinked():
    rec = _recording(is_combined=True)
    assert match_recording(rec, []) == []
