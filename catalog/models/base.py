from django.db import models


class TimeStamped(models.Model):
    """Mixin: created/updated timestamps on every row."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Reviewable(TimeStamped):
    """A fact emitted by ingestion as a proposal pending admin review (brief §7).

    Nothing reviewed=False is shown to the public; the admin confirms facts
    before they become visible. `confidence` is the ingester's self-scoring.
    """

    reviewed = models.BooleanField(default=False)
    confidence = models.FloatField(null=True, blank=True)

    class Meta:
        abstract = True
