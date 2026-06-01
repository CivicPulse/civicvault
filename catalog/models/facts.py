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
