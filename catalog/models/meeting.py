from django.db import models

from .base import TimeStamped
from .org import Jurisdiction, Organization, Source


class Meeting(TimeStamped):
    """The ingestion anchor: one meeting record (brief §7)."""

    # Maps the archive's folder type-slug to a Kind (brief §4.1).
    SLUG_TO_KIND = {
        "committee-meeting": "committee",
        "board-meeting": "board",
        "board-agenda": "board_agenda",
        "called-board-meeting": "called_board",
        "called-board-meeting-policy-review": "called_board",
    }

    class Kind(models.TextChoices):
        COMMITTEE = "committee", "Committee Meeting"
        BOARD = "board", "Board Meeting"
        BOARD_AGENDA = "board_agenda", "Board Agenda"
        CALLED_BOARD = "called_board", "Called Board Meeting"
        OTHER = "other", "Other"

    body = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="meetings")
    jurisdiction = models.ForeignKey(
        Jurisdiction, null=True, blank=True, on_delete=models.SET_NULL, related_name="meetings"
    )
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="meetings"
    )
    date = models.DateField()
    start_time = models.TimeField(null=True, blank=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    raw_type_slug = models.CharField(max_length=128, blank=True)
    title = models.CharField(max_length=512, blank=True)
    source_meeting_id = models.CharField(max_length=64, blank=True)
    source_url = models.URLField(max_length=1024, blank=True)
    source_path = models.CharField(max_length=1024, blank=True)
    slug = models.SlugField(max_length=255)

    class Meta:
        ordering = ["-date", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_meeting_id"],
                name="uniq_meeting_per_source_id",
            ),
            models.UniqueConstraint(
                fields=["jurisdiction", "slug"],
                name="uniq_meeting_slug_per_jurisdiction",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(jurisdiction__isnull=True),
                name="uniq_global_meeting_slug",
            ),
        ]

    @classmethod
    def kind_from_slug(cls, slug):
        """Map a raw folder type-slug to a Kind; unknown slugs → OTHER (§4.1)."""
        return cls.SLUG_TO_KIND.get(slug, cls.Kind.OTHER)

    def __str__(self):
        return f"{self.date} {self.get_kind_display()}"


class AgendaItem(TimeStamped):
    """One numbered item within a meeting's agenda (brief §7)."""

    class ItemType(models.TextChoices):
        ACTION = "action", "Action"
        PRESENTATION = "presentation", "Presentation"
        INFORMATION = "information", "Information"
        OTHER = "other", "Other"

    class ReadingStage(models.TextChoices):
        FIRST = "first", "First Reading"
        SECOND = "second", "Second Reading"

    class OutcomeStatus(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        TABLED = "tabled", "Tabled"
        POSTPONED = "postponed", "Postponed"
        UNANIMOUS = "unanimous", "Unanimously Approved"
        NONE = "none", "No Outcome"

    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="agenda_items")
    order = models.PositiveIntegerField(default=0)
    code = models.CharField(max_length=32, blank=True)
    title = models.CharField(max_length=512)
    item_type = models.CharField(max_length=32, choices=ItemType.choices, default=ItemType.OTHER)
    reading_stage = models.CharField(max_length=16, choices=ReadingStage.choices, blank=True)
    outcome_text = models.TextField(blank=True)
    outcome_status = models.CharField(
        max_length=16, choices=OutcomeStatus.choices, default=OutcomeStatus.NONE
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    amount_text = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["meeting", "order"]
        constraints = [
            models.UniqueConstraint(
                fields=["meeting", "order"], name="uniq_agendaitem_meeting_order"
            )
        ]

    def __str__(self):
        return f"{self.code} {self.title}".strip()
