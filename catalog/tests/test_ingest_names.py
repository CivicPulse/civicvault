import pytest

from catalog.ingest.names import normalize_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ms. Myrtice Johnson", "Myrtice Johnson"),
        ("Mr. Daryl Morton", "Daryl Morton"),
        ("Mrs. Kristin Hanlon", "Kristin Hanlon"),
        ("Dr. Henry Ficklin", "Henry Ficklin"),
        ("Ms.  Myrtice Johnson", "Myrtice Johnson"),  # double space after honorific
        (" Dr. Sundra Woodford", "Sundra Woodford"),  # leading space (variant 2 quirk)
        ("Ms. Myrtice Johnson, President", "Myrtice Johnson"),  # trailing role
        ("Dr. Lisa Garrett-Boyd, Board Member", "Lisa Garrett-Boyd"),
        # Leading professional titles are stripped (grounded in the real archive).
        ("Attorney Roy Miller", "Roy Miller"),
        ("Superintendent Dan Sims", "Dan Sims"),
        ("President Lester Miller", "Lester Miller"),
        ("Mayor Lester Miller", "Lester Miller"),
        ("Judge Verda Colvin", "Verda Colvin"),
        ("Pastor Mike Lee", "Mike Lee"),
        ("Rev. John Doe", "John Doe"),
        ("Reverend John Doe", "John Doe"),
        ("Coach Pat Riley", "Pat Riley"),
        ("Chairperson Smith", "Smith"),
        # Multi-word titles: an optional Vice/Assistant/Deputy modifier is consumed too.
        ("Vice President Daryl Morton", "Daryl Morton"),
        ("Assistant Superintendent Jane Roe", "Jane Roe"),
        # A stacked honorific + title in either order is fully stripped.
        ("Rev. Dr. John Doe", "John Doe"),
        ("Jessican Strohmetz", "Jessican Strohmetz"),  # OCR typo preserved verbatim
        ("Miss Jane Doe", "Jane Doe"),
        # Guards: ordinary names whose first word merely *starts* like a title/honorific
        # must NOT be stripped (no trailing separator after the prefix).
        ("Daryl Morton", "Daryl Morton"),
        ("Drew Carey", "Drew Carey"),  # "Dr" honorific must not eat "Drew"
        ("Presley Adams", "Presley Adams"),  # "President" must not eat "Presley"
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_role_hint_via_split():
    from catalog.ingest.names import split_name_and_role

    name, role = split_name_and_role("Ms. Myrtice Johnson, President")
    assert name == "Myrtice Johnson"
    assert role == "President"

    name, role = split_name_and_role("Dr. Henry Ficklin")
    assert name == "Henry Ficklin"
    assert role == ""
