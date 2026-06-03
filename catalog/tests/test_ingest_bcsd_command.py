import shutil

import pytest
from django.core.management import call_command

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Jurisdiction,
    Meeting,
    Motion,
    Source,
    Vote,
)
from catalog.tests.fixtures import FIXTURES_DIR


def _stage_pair(tmp_path):
    """Lay out the two meeting folders as the archive does."""
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
