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
        ("Attorney Roy Miller", "Attorney Roy Miller"),  # "Attorney" is not a known honorific
        ("Jessican Strohmetz", "Jessican Strohmetz"),  # OCR typo preserved verbatim
        ("Miss Jane Doe", "Jane Doe"),
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
