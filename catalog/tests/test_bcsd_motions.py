from catalog.ingest.bcsd.motions import parse_outcome_block


def test_variant1_bulleted_unanimous():
    block = [
        "The Board authorized the purchase in an amount not to exceed $5,515,711.09.",
        "",
        "- Motion made by: Dr. Henry Ficklin",
        "- Motion seconded by: Dr. Lisa Garrett-Boyd",
        "",
        "_Voting results:_ Unanimously approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert "5,515,711.09" in text
    assert len(motions) == 1
    assert motions[0].kind == "simple"
    assert motions[0].moved_by.full_name == "Henry Ficklin"
    assert motions[0].seconded_by.full_name == "Lisa Garrett-Boyd"
    assert motions[0].status == "unanimous"
    assert votes == []


def test_variant2_non_bulleted():
    block = [
        "The Board voted to enter into Executive Session at 6:03 p.m.",
        "",
        "Motion made by: Dr. Sundra Woodford",
        "",
        "Motion seconded by: Mr. Daryl Morton",
        "",
        "Voting: Unanimously Approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 1
    assert motions[0].moved_by.full_name == "Sundra Woodford"
    assert motions[0].status == "unanimous"


def test_variant3_initial_and_amended():
    block = [
        "The Board entertained a motion ... SureLock Technology ... $2,919,243.58 ...",
        "Upon a request for clarification ... the initial motion was amended as follows:",
        "The Board authorizes the purchase order ... contingent upon the passage of FSS-11 ...",
        "",
        "Initial Motion made by: Dr. Lisa Garrett-Boyd",
        "",
        "Initial Motion seconded by: Ms.  Myrtice Johnson",
        "",
        "Voting: Unanimously Approved",
        "",
        "Amended Motion made by: Mr. James Freeman",
        "",
        "Voting: Unanimously Approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 2
    assert motions[0].kind == "initial"
    assert motions[0].sequence == 0
    assert motions[0].seconded_by.full_name == "Myrtice Johnson"  # double-space normalized
    assert motions[1].kind == "amended"
    assert motions[1].sequence == 1
    assert motions[1].moved_by.full_name == "James Freeman"
    assert motions[1].seconded_by is None


def test_variant3_amended_without_intervening_voting_line():
    # Board "APPROVAL OF AGENDA": initial+seconded, then amended directly, one Voting line.
    block = [
        "A motion was entertained to approve the agenda.",
        "A motion was then made to amend the agenda, removing FSS-2 and PR-2 ...",
        "",
        "Initial Motion made by: Dr. Henry Ficklin",
        "",
        "Initial Motion seconded by: Dr. Sundra Woodford",
        "",
        "Amended Motion made by: Mr. James Freeman",
        "",
        "Voting: Unanimously Approved",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 2
    assert motions[0].kind == "initial"
    assert motions[0].moved_by.full_name == "Henry Ficklin"
    assert motions[0].seconded_by.full_name == "Sundra Woodford"
    assert motions[0].status == "none"  # no explicit voting line for the initial motion
    assert motions[1].kind == "amended"
    assert motions[1].moved_by.full_name == "James Freeman"
    assert motions[1].seconded_by is None
    assert motions[1].status == "unanimous"


def test_variant4_per_person_roll_call():
    block = [
        "The Board approved the Consent Agenda as revised ...",
        "",
        "- Motion made by: Mr. James Freeman",
        "- Motion seconded by: Mr. Daryl Morton",
        "",
        "_Voting results:_ Unanimously approved",
        "",
        "- Yes: Ms. Myrtice Johnson",
        "- Yes: Mr. Daryl Morton",
        "- Yes: Mrs. Kristin Hanlon",
        "- Yes: Dr. Henry Ficklin",
        "- Yes: Mr. Barney Hester",
        "- Yes: Dr. Sundra Woodford",
        "- Yes: Mr. James Freeman",
        "- Yes: Dr. Lisa Garrett-Boyd",
    ]
    text, motions, votes = parse_outcome_block(block)
    assert len(motions) == 1
    assert len(votes) == 8
    assert all(v.value == "yea" for v in votes)
    assert votes[0].person.full_name == "Myrtice Johnson"


def test_no_motion_block_returns_text_only():
    block = ["This item was informational; no action taken."]
    text, motions, votes = parse_outcome_block(block)
    assert motions == []
    assert votes == []
    assert text.startswith("This item")
