from catalog.models.base import Reviewable, TimeStamped


def test_bases_are_abstract():
    assert TimeStamped._meta.abstract is True
    assert Reviewable._meta.abstract is True


def test_reviewable_defaults():
    field_names = {f.name for f in Reviewable._meta.get_fields()}
    assert {"created_at", "updated_at", "reviewed", "confidence"} <= field_names
    reviewed = Reviewable._meta.get_field("reviewed")
    assert reviewed.default is False
