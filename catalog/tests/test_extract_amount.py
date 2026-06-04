"""extract_amount() captures a contract figure ONLY when a contract cue precedes it,
and preserves the verbatim phrase. Governance thresholds yield no amount."""

from decimal import Decimal

from catalog.ingest.bcsd.minutes_md import extract_amount


def test_in_the_amount_not_to_exceed():
    amt, phrase = extract_amount(
        "Approved the purchase in an amount not to exceed $255,500.00 to purchase desk shields."
    )
    assert amt == Decimal("255500.00")
    assert phrase == "in an amount not to exceed $255,500.00"


def test_in_the_amount_of():
    amt, phrase = extract_amount("Motion carried in the amount of $1,000.00.")
    assert amt == Decimal("1000.00")
    assert phrase == "in the amount of $1,000.00"


def test_annual_cost_not_to_exceed():
    amt, phrase = extract_amount(
        "Approved the Academy at an annual cost not to exceed $689,000.00 utilizing funds."
    )
    assert amt == Decimal("689000.00")
    assert "at an annual cost not to exceed $689,000.00" == phrase


def test_aggregate_amount():
    amt, _ = extract_amount(
        "Approved services in an aggregate amount not to exceed $1,190,822.00 for FY 2021-2022."
    )
    assert amt == Decimal("1190822.00")


def test_headline_figure_wins_over_parenthetical_breakdown():
    amt, _ = extract_amount(
        "Approved Elements in an amount not to exceed $439,500.00 "
        "(American Rescue Funds - $250,000.00 and local - $189,500.00)."
    )
    assert amt == Decimal("439500.00")


def test_governance_threshold_has_no_amount():
    assert extract_amount("No contract in excess of $150,000.00 without a proper bond.") == (
        None,
        "",
    )
    assert extract_amount("Surplus items valued less than $5,000.00 may be sold.") == (None, "")
    assert extract_amount("Purchases over $30,000 require board approval.") == (None, "")


def test_no_dollar_figure_at_all():
    assert extract_amount("Approved unanimously.") == (None, "")
    assert extract_amount("") == (None, "")
