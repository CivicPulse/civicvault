import shutil
from unittest import mock

import pytest
from django.contrib.postgres.search import SearchQuery
from django.core.management import call_command

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Motion,
    Source,
    Vote,
)
from catalog.tests.fixtures import FIXTURES_DIR
from catalog.tests.fixtures.pdfs import write_empty_pdf, write_text_pdf


def _stage_pair(tmp_path):
    """Lay out the two meeting folders as the archive does, with a committee files/ dir."""
    specs = [
        ("committee", "2025-04-17_1600_committee-meeting_mid-124789"),
        ("board", "2025-04-17_1830_board-meeting_mid-124791"),
    ]
    root = tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "04"
    for fixture, folder_name in specs:
        dst = root / folder_name
        dst.mkdir(parents=True)
        for fname in ("event.md", "minutes.md", "agenda.md"):
            shutil.copy(FIXTURES_DIR / fixture / fname, dst / fname)
    # Stage two real attachments into the committee folder. hmh.pdf is referenced
    # by committee/event.md's ## Files map (→ FSS-3); the empty one is unmapped.
    # Only 2 of the 60+ mapped files exist on disk → exercises the "map entry,
    # no file on disk → skipped" path for free.
    committee_files = root / "2025-04-17_1600_committee-meeting_mid-124789" / "files"
    committee_files.mkdir()
    write_text_pdf(committee_files / "hmh.pdf")
    write_empty_pdf(committee_files / "unmapped-extra.pdf")
    return root


@pytest.mark.django_db
def test_command_ingests_both_meetings(tmp_path):
    root = _stage_pair(tmp_path)
    call_command("ingest_bcsd", str(root / "2025-04-17_1600_committee-meeting_mid-124789"))
    call_command("ingest_bcsd", str(root / "2025-04-17_1830_board-meeting_mid-124791"))

    assert Meeting.objects.count() == 2
    assert Jurisdiction.objects.filter(slug="bibb-county-boe").exists()
    assert Source.objects.filter(adapter="bcsd").exists()

    committee = Meeting.objects.get(source_meeting_id="124789")
    assert committee.kind == Meeting.Kind.COMMITTEE
    # FSS-8 carries an initial + amended motion.
    fss8 = AgendaItem.objects.get(meeting=committee, code="FSS-8")
    assert Motion.objects.filter(agenda_item=fss8).count() == 2

    board = Meeting.objects.get(source_meeting_id="124791")
    # Consent en-bloc roll call (8) + PS-6 roll call (8) = 16 captured votes.
    # The procedural "### ADJOURN" roll call is intentionally NOT materialized
    # (only coded "####" items become AgendaItems), so it is excluded here.
    assert Vote.objects.filter(agenda_item__meeting=board).count() == 16
    # Visitors captured as speaker appearances.
    assert Appearance.objects.filter(meeting=board, role=Appearance.Role.SPEAKER).count() >= 2

    # Provenance: every vote is cited into the minutes.
    for vote in Vote.objects.all():
        assert Citation.objects.for_fact(vote).count() >= 1

    # Nothing is auto-reviewed.
    assert not Vote.objects.filter(reviewed=True).exists()
    assert not Appearance.objects.filter(reviewed=True).exists()


@pytest.mark.django_db
def test_command_is_idempotent(tmp_path):
    root = _stage_pair(tmp_path)
    folder = str(root / "2025-04-17_1600_committee-meeting_mid-124789")
    call_command("ingest_bcsd", folder)
    call_command("ingest_bcsd", folder)
    assert Meeting.objects.filter(source_meeting_id="124789").count() == 1
    committee = Meeting.objects.get(source_meeting_id="124789")
    fss8 = AgendaItem.objects.get(meeting=committee, code="FSS-8")
    assert Motion.objects.filter(agenda_item=fss8).count() == 2  # not 4


@pytest.mark.django_db
def test_command_uploads_only_with_flag(tmp_path):
    root = _stage_pair(tmp_path)
    folder = str(root / "2025-04-17_1600_committee-meeting_mid-124789")

    # Default: no --upload → storage is never touched (keeps tests offline).
    with mock.patch("catalog.management.commands.ingest_bcsd.upload_missing") as up:
        call_command("ingest_bcsd", folder)
    up.assert_not_called()

    # With --upload → upload_missing is called for each attachment.
    with mock.patch(
        "catalog.management.commands.ingest_bcsd.upload_missing", return_value=False
    ) as up:
        call_command("ingest_bcsd", folder, "--upload")
    assert up.call_count == 2  # both staged committee PDFs (hmh.pdf + unmapped-extra.pdf)
    assert all(c.args[0].startswith("BCSD/") for c in up.call_args_list)


@pytest.mark.django_db
def test_command_ingests_attachment_documents(tmp_path):
    root = _stage_pair(tmp_path)
    call_command("ingest_bcsd", str(root / "2025-04-17_1600_committee-meeting_mid-124789"))

    committee = Meeting.objects.get(source_meeting_id="124789")
    attachments = Document.objects.filter(meeting=committee, r2_key__startswith="BCSD/")
    # Exactly the two files staged on disk (the other mapped files are silently skipped).
    assert attachments.count() == 2

    hmh = attachments.get(r2_key__endswith="/files/hmh.pdf")
    assert hmh.agenda_item is not None and hmh.agenda_item.code == "FSS-3"
    assert hmh.ocr_status == Document.OCRStatus.HAS_TEXT
    # search_vector populated by the trigger → full-text query matches.
    assert attachments.filter(search_vector=SearchQuery("chromebooks")).filter(pk=hmh.pk).exists()

    extra = attachments.get(r2_key__endswith="/files/unmapped-extra.pdf")
    assert extra.agenda_item is None
    assert extra.ocr_status == Document.OCRStatus.OCR_NEEDED
    # The empty/ocr_needed doc has no text → not indexed (trigger leaves it unmatched).
    assert (
        not attachments.filter(search_vector=SearchQuery("chromebooks"))
        .filter(pk=extra.pk)
        .exists()
    )


@pytest.mark.django_db
def test_command_ingests_nested_personnel_without_duplicate_votes(tmp_path):
    folder_name = "2025-06-19_1600_committee-meeting_mid-999001"
    dst = tmp_path / "BCSD_BOE_MEETINGS" / "2025" / "06" / folder_name
    dst.mkdir(parents=True)
    for fname in ("event.md", "minutes.md"):
        shutil.copy(FIXTURES_DIR / "personnel" / fname, dst / fname)

    # Must not raise the duplicate-vote IntegrityError.
    call_command("ingest_bcsd", str(dst))

    meeting = Meeting.objects.get(source_meeting_id="999001")

    ps1 = AgendaItem.objects.get(meeting=meeting, code="PS-1")
    ps2 = AgendaItem.objects.get(meeting=meeting, code="PS-2")
    assert Vote.objects.filter(agenda_item=ps1).count() == 5
    assert Vote.objects.filter(agenda_item=ps2).count() == 5

    # Executive Session keeps its motions and carries NO votes.
    exec_item = AgendaItem.objects.get(meeting=meeting, title="Executive Session for Personnel Matters")
    assert Vote.objects.filter(agenda_item=exec_item).count() == 0
    assert Motion.objects.filter(agenda_item=exec_item).count() == 2

    # Appointment roll calls attach to the appointment items; the abstention survives.
    director = AgendaItem.objects.get(meeting=meeting, title="Director of Research")
    asst = AgendaItem.objects.get(meeting=meeting, title="Assistant Principal Southfield")
    assert Vote.objects.filter(agenda_item=director).count() == 5
    assert Vote.objects.filter(agenda_item=asst, value=Vote.Value.ABSTAIN).count() == 1

    # 5 + 5 + 5 + 5 = 20 votes total; none lost, none duplicated.
    assert Vote.objects.filter(agenda_item__meeting=meeting).count() == 20
