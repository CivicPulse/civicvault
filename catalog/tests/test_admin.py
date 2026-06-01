from django.contrib import admin

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
)

EXPECTED = [
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
]


def test_all_catalog_models_are_registered():
    for model in EXPECTED:
        assert admin.site.is_registered(model), f"{model.__name__} not registered in admin"
