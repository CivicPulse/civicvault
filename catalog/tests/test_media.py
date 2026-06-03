import datetime

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import IntegrityError

from catalog.models import (
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Transcript,
    TranscriptSegment,
)


@pytest.mark.django_db
def test_recording_with_segments_and_two_coverages():
    """A combined committee+board recording has two MeetingCoverage windows (§6.3)."""
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    committee = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.COMMITTEE, slug="c1"
    )
    board = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b1"
    )
    media = MediaAsset.objects.create(
        kind=MediaAsset.Kind.VIDEO, youtube_id="abc123XYZ_0", duration_seconds=13486
    )
    transcript = Transcript.objects.create(media=media, origin=Transcript.Origin.YOUTUBE_CAPTIONS)
    seg = TranscriptSegment.objects.create(
        transcript=transcript, start=12.5, end=15.0, text="call the meeting to order"
    )
    MeetingCoverage.objects.create(media=media, meeting=committee, start_offset=0, end_offset=7000)
    MeetingCoverage.objects.create(media=media, meeting=board, start_offset=7000, end_offset=None)

    assert media.coverages.count() == 2
    # The segment start is the absolute YouTube ?t= offset.
    assert seg.start == 12.5
    assert transcript.segments.count() == 1


@pytest.mark.django_db
def test_coverage_unique_per_media_meeting():
    from django.db import IntegrityError

    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.BOARD, slug="b2"
    )
    media = MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="zzz")
    MeetingCoverage.objects.create(media=media, meeting=meeting)
    with pytest.raises(IntegrityError):
        MeetingCoverage.objects.create(media=media, meeting=meeting)


@pytest.mark.django_db
def test_youtube_id_is_unique_when_present():
    MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="dupid")
    with pytest.raises(IntegrityError):
        MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="dupid")


@pytest.mark.django_db
def test_blank_youtube_id_is_allowed_multiple_times():
    MediaAsset.objects.create(kind=MediaAsset.Kind.AUDIO, youtube_id="")
    MediaAsset.objects.create(kind=MediaAsset.Kind.AUDIO, youtube_id="")  # no error


@pytest.mark.django_db
def test_segment_search_vector_trigger_populates_on_insert():
    media = MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="seg1")
    transcript = Transcript.objects.create(media=media, origin=Transcript.Origin.YOUTUBE_CAPTIONS)
    seg = TranscriptSegment.objects.create(
        transcript=transcript, start=0.0, end=2.0, text="chromebooks for students"
    )
    qs = TranscriptSegment.objects.filter(pk=seg.pk)
    assert qs.filter(search_vector=SearchQuery("chromebooks")).exists()


@pytest.mark.django_db
def test_segment_search_vector_trigger_updates_on_text_change():
    media = MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="seg2")
    transcript = Transcript.objects.create(media=media, origin=Transcript.Origin.YOUTUBE_CAPTIONS)
    seg = TranscriptSegment.objects.create(
        transcript=transcript, start=0.0, end=2.0, text="microsoft"
    )
    seg.text = "lenovo lease"
    seg.save()
    qs = TranscriptSegment.objects.filter(pk=seg.pk)
    assert qs.filter(search_vector=SearchQuery("lenovo")).exists()
    assert not qs.filter(search_vector=SearchQuery("microsoft")).exists()
