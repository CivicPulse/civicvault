import datetime
import shutil
from pathlib import Path

from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.tests.fixtures import FIXTURES_DIR


def _make_folder(tmp_path: Path, fixture: str, folder_name: str, *, with_minutes=True) -> Path:
    src = FIXTURES_DIR / fixture
    dst = tmp_path / folder_name
    dst.mkdir()
    shutil.copy(src / "event.md", dst / "event.md")
    shutil.copy(src / "agenda.md", dst / "agenda.md")
    if with_minutes:
        shutil.copy(src / "minutes.md", dst / "minutes.md")
    return dst


def test_committee_meeting_parsed(tmp_path):
    folder = _make_folder(tmp_path, "committee", "2025-04-17_1600_committee-meeting_mid-124789")
    pm = parse_meeting_folder(folder)
    assert pm.date == datetime.date(2025, 4, 17)
    assert pm.start_time == datetime.time(16, 0)
    assert pm.kind_slug == "committee-meeting"
    assert pm.source_meeting_id == "124789"
    assert pm.has_minutes is True
    assert len(pm.roster) == 8

    by_code = {it.code: it for it in pm.agenda_items if it.code}
    fss3 = by_code["FSS-3"]
    assert fss3.outcome_status == "unanimous"
    assert len(fss3.motions) == 1
    assert fss3.motions[0].moved_by.full_name == "Henry Ficklin"
    assert "hmh.pdf" in fss3.file_names
    assert len(by_code["FSS-8"].motions) == 2

    # Substring guard: FSS-1 must NOT absorb FSS-10/FSS-11 attachments.
    assert by_code["FSS-1"].file_names == ("fss-1m-1.PPT",)


def test_board_roll_call_carried_through(tmp_path):
    folder = _make_folder(tmp_path, "board", "2025-04-17_1830_board-meeting_mid-124791")
    pm = parse_meeting_folder(folder)
    assert pm.kind_slug == "board-meeting"
    anchor = next(it for it in pm.agenda_items if it.title.startswith("Confirmation of Minutes"))
    assert len(anchor.votes) == 8
    speakers = {a.person.full_name for a in pm.appearances if a.role == "speaker"}
    assert {"Attorney Roy Miller", "Jessican Strohmetz"} <= speakers


def test_minutes_absent_falls_back_to_agenda(tmp_path):
    folder = _make_folder(
        tmp_path, "committee", "2025-04-17_1600_committee-meeting_mid-124789", with_minutes=False
    )
    pm = parse_meeting_folder(folder)
    assert pm.has_minutes is False
    assert len(pm.agenda_items) > 0
    assert all(not it.motions and not it.votes for it in pm.agenda_items)
    assert pm.roster == ()
