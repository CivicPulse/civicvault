from django.db import models

from .base import Reviewable
from .meeting import AgendaItem, Meeting
from .org import Person


class Vote(Reviewable):
    """A per-member vote on an agenda item (brief §7). Only materialized where an
    explicit roll call exists; unanimous outcomes live on AgendaItem (§9 #13)."""

    class Value(models.TextChoices):
        YEA = "yea", "Yea"
        NAY = "nay", "Nay"
        ABSTAIN = "abstain", "Abstain"
        ABSENT = "absent", "Absent"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="votes")
    agenda_item = models.ForeignKey(AgendaItem, on_delete=models.CASCADE, related_name="votes")
    value = models.CharField(max_length=16, choices=Value.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["person", "agenda_item"], name="uniq_vote_person_item")
        ]

    def __str__(self):
        return f"{self.person} {self.value} on {self.agenda_item}"


class Appearance(Reviewable):
    """A person's appearance at a meeting in some role (brief §7)."""

    class Role(models.TextChoices):
        MEMBER = "member", "Member"
        SPEAKER = "speaker", "Speaker"
        PRESENTER = "presenter", "Presenter"
        STAFF = "staff", "Staff"
        INVOCATION = "invocation", "Invocation"
        PLEDGE = "pledge", "Pledge of Allegiance"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="appearances")
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, related_name="appearances")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)

    def __str__(self):
        return f"{self.person} as {self.role} at {self.meeting}"


class Motion(Reviewable):
    """A motion recorded against an agenda item (brief §5.2). A single item may
    carry an initial + amended pair (FSS-8) or a consent-agenda anchor motion that
    approves many items en bloc. Movers/seconders are proposed Persons; the
    per-member roll call (where present) is stored as Vote rows on the item."""

    class Kind(models.TextChoices):
        SIMPLE = "simple", "Simple"
        INITIAL = "initial", "Initial"
        AMENDED = "amended", "Amended"

    class Status(models.TextChoices):
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        UNANIMOUS = "unanimous", "Unanimously Approved"
        NONE = "none", "No Recorded Result"

    agenda_item = models.ForeignKey(AgendaItem, on_delete=models.CASCADE, related_name="motions")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SIMPLE)
    sequence = models.PositiveSmallIntegerField(default=0)
    moved_by = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="motions_moved"
    )
    seconded_by = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.SET_NULL, related_name="motions_seconded"
    )
    result_text = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NONE)

    class Meta:
        ordering = ["agenda_item", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["agenda_item", "sequence"], name="uniq_motion_item_sequence"
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_motion",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} motion on {self.agenda_item} ({self.status})"
