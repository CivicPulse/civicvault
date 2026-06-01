import datetime

import pytest

from catalog.ingest.bcsd.foldername import ParsedFolderName, parse_folder_name


def test_parse_committee_folder():
    fn = parse_folder_name("2025-04-17_1600_committee-meeting_mid-124789")
    assert fn == ParsedFolderName(
        date=datetime.date(2025, 4, 17),
        start_time=datetime.time(16, 0),
        type_slug="committee-meeting",
        meeting_id="124789",
    )


def test_parse_board_folder():
    fn = parse_folder_name("2025-04-17_1830_board-meeting_mid-124791")
    assert fn.start_time == datetime.time(18, 30)
    assert fn.type_slug == "board-meeting"
    assert fn.meeting_id == "124791"


def test_parse_multiword_type_slug():
    fn = parse_folder_name("2014-07-29_1800_called-board-meeting-policy-review_mid-39007")
    assert fn.type_slug == "called-board-meeting-policy-review"
    assert fn.meeting_id == "39007"


def test_invalid_folder_name_raises():
    with pytest.raises(ValueError):
        parse_folder_name("not-a-meeting-folder")
