from catalog.ingest.bcsd.event_md import parse_event_md
from catalog.tests.fixtures import fixture_text


def test_committee_event_metadata():
    ev = parse_event_md(fixture_text("committee", "event.md"))
    assert ev.meeting_id == "124789"
    assert ev.meeting_type == "Committee Meeting"
    assert ev.source_url.endswith("MID=124789")


def test_committee_event_agenda_items_have_codes_and_types():
    ev = parse_event_md(fixture_text("committee", "event.md"))
    by_code = {it.code: it for it in ev.agenda_items if it.code}
    # FSS-3 is an ACTION item.
    assert "FSS-3" in by_code
    assert by_code["FSS-3"].item_type == "action"
    assert by_code["FSS-3"].title.startswith("Mathematics Instructional Resources")
    # PR-1 carries a Second Reading stage.
    assert by_code["PR-1"].reading_stage == "second"
    # PR-4 is INFORMATION + First Reading.
    assert by_code["PR-4"].item_type == "information"
    assert by_code["PR-4"].reading_stage == "first"
    # HTML entity unescaped in a title.
    assert "&amp;" not in by_code["FSS-4"].title
    assert "&" in by_code["FSS-4"].title


def test_committee_event_files_map():
    ev = parse_event_md(fixture_text("committee", "event.md"))
    # The HMH quote pdf is attributed to FSS-3.
    assert ev.files["hmh.pdf"].startswith("ii. FSS-3")
    # Order is preserved and every line captured (60 attachments downloaded).
    assert len(ev.files) >= 55


def test_board_event_files_map_small():
    ev = parse_event_md(fixture_text("board", "event.md"))
    assert ev.meeting_id == "124791"
    assert "supt-board-041725-ppt.pptx" in ev.files


def test_board_dash_separated_code_title_is_clean():
    ev = parse_event_md(fixture_text("board", "event.md"))
    by_code = {it.code: it for it in ev.agenda_items if it.code}
    assert by_code["PS-1"].title == "Certified Personnel Report"
    assert not by_code["PS-1"].title.startswith("-")
