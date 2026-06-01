import datetime

import pytest

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
