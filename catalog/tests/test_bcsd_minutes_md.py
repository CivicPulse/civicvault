import pytest

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


def test_personnel_five_hash_subitems_separate_roll_calls():
    parsed = parse_minutes_md(fixture_text("personnel", "minutes.md"))

    ps1 = parsed.outcomes["PS-1"]
    ps2 = parsed.outcomes["PS-2"]
    assert len(ps1.votes) == 5
    assert len(ps2.votes) == 5
    assert all(v.value == "yea" for v in ps1.votes)

    # The four-hash Executive Session item keeps only its two un-rolled motions;
    # the PS roll calls must NOT have been absorbed into it.
    exec_item = parsed.outcomes["Executive Session for Personnel Matters"]
    assert len(exec_item.votes) == 0
    assert len(exec_item.motions) == 2
    assert exec_item.outcome_status == "unanimous"

    # PS-1 and PS-2 each carry their own single roll call (no duplicate voter).
    for code in ("PS-1", "PS-2"):
        names = [v.person.full_name for v in parsed.outcomes[code].votes]
        assert len(names) == len(set(names)), f"duplicate voter in {code}"


def test_personnel_six_hash_escaped_ordinal_appointments_separate():
    parsed = parse_minutes_md(fixture_text("personnel", "minutes.md"))

    director = parsed.outcomes["Director of Research"]
    asst = parsed.outcomes["Assistant Principal Southfield"]
    assert len(director.votes) == 5
    assert all(v.value == "yea" for v in director.votes)

    # The abstention on the second appointment must survive as its own roll call —
    # this per-decision difference is the signal the coarse parse destroyed.
    assert len(asst.votes) == 5
    assert sum(1 for v in asst.votes if v.value == "abstain") == 1
    abstainer = next(v for v in asst.votes if v.value == "abstain")
    assert abstainer.person.full_name == "Eve Evans"

    # PS-3's own block is now empty (its roll calls moved to the appointments).
    assert len(parsed.outcomes["PS-3"].votes) == 0

    # Global invariant — now satisfiable: NO agenda item contains the same voter
    # twice anywhere in the fixture.
    for oc in parsed.outcomes.values():
        names = [v.person.full_name for v in oc.votes]
        assert len(names) == len(set(names)), f"duplicate voter in {oc.code or oc.title!r}"


def test_repeated_voter_in_one_item_raises():
    # A single item whose block contains two roll calls naming the same person —
    # the malformed shape the guard must catch.
    text = """## Meeting Minutes

### Attendance

#### Voting Members

- Ms. Alice Adams, President
- Mr. Bob Brown, Board Member

### IV. SOME COMMITTEE

#### i. SC-1 Some Action

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown

_Voting results:_

- Yes: Ms. Alice Adams
- Yes: Mr. Bob Brown
"""
    with pytest.raises(ValueError, match=r"Duplicate vote for 'Alice Adams'"):
        parse_minutes_md(text)
