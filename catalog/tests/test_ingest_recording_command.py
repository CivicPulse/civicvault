import datetime
from pathlib import Path

import pytest
from django.core.management import call_command

from catalog.models import (
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Source,
    TranscriptSegment,
)

FIX = Path("catalog/tests/fixtures/recordings/BCSD_MEETING_RECORDINGS")
INFO_NAME = "test_committee_and_board_1_19_2023_TESTvideo01_.info.json"


@pytest.fixture
def boe(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bibb-county-boe")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    return jur, body


@pytest.mark.django_db
def test_command_combined_creates_two_coverage_windows(boe):
    jur, body = boe
    committee = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(16, 0),
        kind=Meeting.Kind.COMMITTEE,
        slug="c",
    )
    board = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(18, 30),
        kind=Meeting.Kind.BOARD,
        slug="b",
    )
    call_command("ingest_recording", str(FIX / INFO_NAME))

    media = MediaAsset.objects.get(youtube_id="TESTvideo01")
    assert TranscriptSegment.objects.filter(transcript__media=media).exists()
    covs = MeetingCoverage.objects.filter(media=media).order_by("start_offset")
    assert covs.count() == 2
    assert covs[0].meeting == committee and covs[0].start_offset == 0.0
    assert covs[1].meeting == board and covs[1].end_offset is None
    assert covs[0].end_offset == covs[1].start_offset  # the split offset
    assert Source.objects.filter(slug="bcsd-meeting-recordings").exists()


@pytest.mark.django_db
def test_command_no_matching_meeting_is_unlinked(boe):
    # No Meeting rows on the recording date → unlinked MediaAsset, zero coverage.
    call_command("ingest_recording", str(FIX / INFO_NAME))
    media = MediaAsset.objects.get(youtube_id="TESTvideo01")
    assert MeetingCoverage.objects.filter(media=media).count() == 0


@pytest.mark.django_db
def test_command_non_meeting_video_is_unlinked_even_near_meeting(boe, tmp_path):
    jur, body = boe
    Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(16, 0),
        kind=Meeting.Kind.COMMITTEE,
        slug="c",
    )
    Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2023, 1, 19),
        start_time=datetime.time(18, 30),
        kind=Meeting.Kind.BOARD,
        slug="b",
    )
    info = tmp_path / "show_up_SHOWvid2_.info.json"
    info.write_text(
        '{"id": "SHOWvid2", "title": "Show Up Program January 20 2023 Elementary", '
        '"duration": 60, "upload_date": "20230120", "webpage_url": "https://youtu.be/SHOWvid2"}'
    )
    call_command("ingest_recording", str(info))
    media = MediaAsset.objects.get(youtube_id="SHOWvid2")
    assert MeetingCoverage.objects.filter(media=media).count() == 0


@pytest.mark.django_db
def test_command_whisper_used_when_no_vtt(boe, tmp_path, monkeypatch):
    # Stage an info.json with no sibling .vtt.
    info = tmp_path / "novtt_WHISPERvid1_.info.json"
    info.write_text(
        '{"id": "WHISPERvid1", "title": "Board Meeting 5/5/2023", '
        '"duration": 30, "upload_date": "20230506", "webpage_url": "https://youtu.be/WHISPERvid1"}'
    )
    from catalog.ingest.ir import ParsedTranscriptSegment

    monkeypatch.setattr(
        "catalog.management.commands.ingest_recording.transcribe_flac",
        lambda path, **kw: (ParsedTranscriptSegment(0.0, 1.0, "whispered text"),),
    )
    # Also stage a fake .flac so the command finds something to transcribe.
    (tmp_path / "novtt_WHISPERvid1_.flac").write_bytes(b"\x00")

    call_command("ingest_recording", str(info), "--whisper")
    media = MediaAsset.objects.get(youtube_id="WHISPERvid1")
    seg = TranscriptSegment.objects.get(transcript__media=media)
    assert seg.text == "whispered text"
    assert media.transcripts.first().origin == media.transcripts.first().Origin.WHISPER
