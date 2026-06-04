from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from .base import TimeStamped
from .meeting import Meeting
from .org import Source


class MediaAsset(TimeStamped):
    """One recording or media file (brief §7). One per recording/file."""

    class Kind(models.TextChoices):
        VIDEO = "video", "Video"
        AUDIO = "audio", "Audio"
        PDF = "pdf", "PDF"
        IMAGE = "image", "Image"

    class AccessLevel(models.TextChoices):
        PUBLIC = "public", "Public"
        RESTRICTED = "restricted", "Restricted"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    r2_key = models.CharField(max_length=1024, blank=True)
    youtube_id = models.CharField(max_length=16, blank=True)
    source_url = models.URLField(max_length=1024, blank=True)
    recorded_on = models.DateField(null=True, blank=True)  # from title date (§6.2)
    upload_date = models.DateField(null=True, blank=True)  # from info.json (§5.5)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    access_level = models.CharField(
        max_length=16, choices=AccessLevel.choices, default=AccessLevel.PUBLIC
    )
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="media_assets"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["r2_key"], condition=~models.Q(r2_key=""), name="uniq_media_r2_key"
            ),
            models.UniqueConstraint(
                fields=["youtube_id"],
                condition=~models.Q(youtube_id=""),
                name="uniq_media_youtube_id",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} {self.youtube_id or self.r2_key}"


class Transcript(TimeStamped):
    """A transcript belongs to a MediaAsset (not a Meeting): it can span two
    meetings (brief §7)."""

    class Origin(models.TextChoices):
        YOUTUBE_CAPTIONS = "youtube_captions", "YouTube Captions"
        WHISPER = "whisper", "faster-whisper"

    media = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="transcripts")
    language = models.CharField(max_length=16, default="en")
    origin = models.CharField(max_length=32, choices=Origin.choices)
    model = models.CharField(max_length=64, blank=True)

    def __str__(self):
        return f"Transcript(media={self.media_id}, {self.origin})"


class TranscriptSegment(models.Model):
    """A timed line of transcript. `start` is the absolute offset in the recording
    = the YouTube ?t= value, powering transcript→video deep links (brief §7, F14)."""

    transcript = models.ForeignKey(Transcript, on_delete=models.CASCADE, related_name="segments")
    start = models.FloatField()
    end = models.FloatField()
    text = models.TextField()
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        ordering = ["transcript", "start"]
        indexes = [GinIndex(fields=["search_vector"], name="gin_segment_search")]

    def __str__(self):
        return f"[{self.start:.1f}-{self.end:.1f}] {self.text[:40]}"


class MeetingCoverage(TimeStamped):
    """Maps a Meeting to the slice of a MediaAsset that covers it (brief §7).
    A combined committee+board recording has two of these."""

    media = models.ForeignKey(MediaAsset, on_delete=models.CASCADE, related_name="coverages")
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="coverages")
    start_offset = models.FloatField(default=0)
    end_offset = models.FloatField(null=True, blank=True)  # null = to end of recording
    split_confirmed = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["media", "meeting"], name="uniq_coverage_media_meeting")
        ]

    def __str__(self):
        return f"coverage(media={self.media_id}, meeting={self.meeting_id})"
