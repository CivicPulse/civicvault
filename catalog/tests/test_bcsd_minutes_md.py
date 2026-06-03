from catalog.ingest.bcsd.minutes_md import parse_minutes_md
from catalog.tests.fixtures import fixture_text


def test_committee_roster():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    names = {p.full_name for p in parsed.roster}
    assert "Myrtice Johnson" in names
    assert "Lisa Garrett-Boyd" in names
    assert len(parsed.roster) == 8
    pres = next(p for p in parsed.roster if p.full_name == "Myrtice Johnson")
    assert pres.role_hint == "President"


def test_committee_invocation_appearance():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    invos = [a for a in parsed.appearances if a.role == "invocation"]
    assert len(invos) == 1
    assert invos[0].person.full_name == "Henry Ficklin"


def test_committee_fss3_outcome_and_motion():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    fss3 = parsed.outcomes["FSS-3"]
    assert "5,515,711.09" in fss3.outcome_text
    assert len(fss3.motions) == 1
    assert fss3.motions[0].moved_by.full_name == "Henry Ficklin"
    assert fss3.outcome_status == "unanimous"


def test_committee_fss8_initial_amended():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    fss8 = parsed.outcomes["FSS-8"]
    assert len(fss8.motions) == 2
    assert fss8.motions[0].kind == "initial"
    assert fss8.motions[1].kind == "amended"


def test_committee_pr2_postponed_status():
    parsed = parse_minutes_md(fixture_text("committee", "minutes.md"))
    pr2 = parsed.outcomes["PR-2"]
    # The item was postponed even though the motion to postpone was unanimous.
    assert pr2.outcome_status == "postponed"


def test_board_roll_call_votes():
    parsed = parse_minutes_md(fixture_text("board", "minutes.md"))
    anchor = parsed.outcomes["Confirmation of Minutes - Board Meetings (2025) - March"]
    assert len(anchor.votes) == 8
    assert all(v.value == "yea" for v in anchor.votes)


def test_board_visitor_and_pledge_appearances():
    parsed = parse_minutes_md(fixture_text("board", "minutes.md"))
    speakers = {a.person.full_name for a in parsed.appearances if a.role == "speaker"}
    assert "Roy Miller" in speakers  # leading "Attorney" title stripped from full_name
    assert "Jessican Strohmetz" in speakers  # OCR typo preserved
    # The raw source text is retained verbatim for provenance/audit.
    assert any(a.person.raw_name == "Attorney Roy Miller" for a in parsed.appearances)
    pledges = [a for a in parsed.appearances if a.role == "pledge"]
    assert len(pledges) == 1
    assert "Nikolai Connor Floore" in pledges[0].person.raw_name
    invos = [a for a in parsed.appearances if a.role == "invocation"]
    assert invos[0].person.full_name == "Arizona Watkins"
