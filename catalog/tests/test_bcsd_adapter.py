import datetime
import shutil
from pathlib import Path

from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.tests.fixtures import FIXTURES_DIR
from catalog.tests.fixtures.pdfs import write_empty_pdf, write_text_pdf


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
    # "Attorney" title is stripped from the display name (raw_name keeps the original).
    assert {"Roy Miller", "Jessican Strohmetz"} <= speakers


def test_minutes_absent_falls_back_to_agenda(tmp_path):
    folder = _make_folder(
        tmp_path, "committee", "2025-04-17_1600_committee-meeting_mid-124789", with_minutes=False
    )
    pm = parse_meeting_folder(folder)
    assert pm.has_minutes is False
    assert len(pm.agenda_items) > 0
    assert all(not it.motions and not it.votes for it in pm.agenda_items)
    assert pm.roster == ()


def _committee_folder_with_files(tmp_path: Path) -> Path:
    folder = (
        tmp_path
        / "BCSD_BOE_MEETINGS"
        / "2025"
        / "04"
        / "2025-04-17_1600_committee-meeting_mid-124789"
    )
    (folder / "files").mkdir(parents=True)
    for fname in ("event.md", "minutes.md", "agenda.md"):
        shutil.copy(FIXTURES_DIR / "committee" / fname, folder / fname)
    # One file that the ## Files map links to FSS-3 (text layer), one unmapped (no text).
    write_text_pdf(folder / "files" / "hmh.pdf")  # mapped to FSS-3 in committee/event.md
    write_empty_pdf(folder / "files" / "unmapped-extra.pdf")
    # A non-PDF file exercises the ("", "unknown") default branch.
    (folder / "files" / "vendor-notes.txt").write_text("plain text, not a pdf")
    return folder


def test_adapter_emits_attachment_documents(tmp_path):
    folder = _committee_folder_with_files(tmp_path)
    parsed = parse_meeting_folder(folder)

    attachments = [d for d in parsed.raw_documents if d.is_attachment]
    by_name = {d.source_path.rsplit("/", 1)[-1]: d for d in attachments}
    assert set(by_name) == {"hmh.pdf", "unmapped-extra.pdf", "vendor-notes.txt"}

    hmh = by_name["hmh.pdf"]
    assert hmh.ocr_status == "has_text"
    assert "chromebooks" in hmh.text
    assert hmh.agenda_item_code == "FSS-3"
    assert hmh.r2_key.endswith(
        "BCSD_BOE_MEETINGS/2025/04/2025-04-17_1600_committee-meeting_mid-124789/files/hmh.pdf"
    )
    assert hmh.r2_key.startswith("BCSD/")

    extra = by_name["unmapped-extra.pdf"]
    assert extra.agenda_item_code is None  # not in the ## Files map → meeting-level
    assert extra.ocr_status == "ocr_needed"

    notes = by_name["vendor-notes.txt"]
    assert notes.ocr_status == "unknown"
    assert notes.text == ""
    assert notes.agenda_item_code is None


def test_adapter_without_files_dir_emits_no_attachments(tmp_path):
    folder = (
        tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "04" / "2025-04-17_1830_board-meeting_mid-124791"
    )
    folder.mkdir(parents=True)
    for fname in ("event.md", "minutes.md", "agenda.md"):
        shutil.copy(FIXTURES_DIR / "board" / fname, folder / fname)
    parsed = parse_meeting_folder(folder)
    assert [d for d in parsed.raw_documents if d.is_attachment] == []
