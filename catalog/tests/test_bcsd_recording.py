import datetime
from pathlib import Path

import pytest

from catalog.ingest.bcsd.recording import parse_recording, parse_title_date

FIX = Path(__file__).parent / "fixtures" / "recordings" / "BCSD_MEETING_RECORDINGS"
INFO = FIX / "test_committee_and_board_1_19_2023_TESTvideo01_.info.json"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Meeting 1/19/2023", datetime.date(2023, 1, 19)),
        ("Meeting 1_19_2023", datetime.date(2023, 1, 19)),
        ("Meeting 04.15.2021", datetime.date(2021, 4, 15)),
        ("Town Hall June 17 2021", datetime.date(2021, 6, 17)),
        ("Town Hall August_19_2021", datetime.date(2021, 8, 19)),
        ("No date here", None),
        ("Bad date 13/40/2023", None),
    ],
)
def test_parse_title_date(title, expected):
    assert parse_title_date(title) == expected


def test_parse_recording_builds_full_record():
    rec = parse_recording(INFO)
    assert rec.youtube_id == "TESTvideo01"
    assert rec.recorded_on == datetime.date(2023, 1, 19)
    assert rec.upload_date == datetime.date(2023, 1, 20)
    assert rec.duration_seconds == 120
    assert rec.is_combined is True
    assert rec.transcript_origin == "youtube_captions"
    assert rec.source_url == "https://www.youtube.com/watch?v=TESTvideo01"
    # the .vtt was found, deduped, and has the two "to order" markers for the splitter
    assert len(rec.segments) >= 3
    assert sum("to order" in s.text for s in rec.segments) == 2


def test_parse_recording_r2_key_uses_bcsd_convention():
    rec = parse_recording(INFO)
    # no .mp4 in the fixture set → blank r2_key (uploads are opt-in)
    assert rec.r2_key == ""


def test_parse_recording_without_vtt_flags_empty_transcript(tmp_path):
    info = tmp_path / "novtt_TESTvideo99_.info.json"
    info.write_text(
        '{"id": "TESTvideo99", "title": "Board Meeting 2/2/2023", '
        '"duration": 60, "upload_date": "20230203", '
        '"webpage_url": "https://youtu.be/TESTvideo99"}'
    )
    rec = parse_recording(info)
    assert rec.segments == ()
    assert rec.transcript_origin == ""


def test_parse_recording_handles_malformed_upload_date(tmp_path):
    info = tmp_path / "bad_TESTvideoXX_.info.json"
    info.write_text(
        '{"id": "TESTvideoXX", "title": "Board Meeting 2/2/2023", '
        '"duration": 60, "upload_date": "2023XX01", "webpage_url": "https://youtu.be/TESTvideoXX"}'
    )
    rec = parse_recording(info)
    assert rec.upload_date is None
    assert rec.recorded_on == datetime.date(2023, 2, 2)


def test_meeting_title_sets_is_meeting_true():
    rec = parse_recording(INFO)
    assert rec.is_meeting is True


def test_non_meeting_title_sets_is_meeting_false(tmp_path):
    info = tmp_path / "show_up_SHOWvid1_.info.json"
    info.write_text(
        '{"id": "SHOWvid1", "title": "Show Up Program January 20 2023 Elementary Program '
        'Southwest High School", "duration": 60, "upload_date": "20230120", '
        '"webpage_url": "https://youtu.be/SHOWvid1"}'
    )
    rec = parse_recording(info)
    assert rec.is_meeting is False
