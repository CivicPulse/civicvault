from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import TimeStamped
from .document import Document
from .media import TranscriptSegment


class CitationManager(models.Manager):
    def for_fact(self, fact):
        """Return every Citation backing a given fact instance."""
        ct = ContentType.objects.get_for_model(fact)
        return self.filter(content_type=ct, object_id=fact.pk)


class Citation(TimeStamped):
    """Provenance backbone (brief §7): attaches ANY fact (Vote, Appearance, …) to
    the evidence for it — a Document (optionally a page) and/or a TranscriptSegment,
    with an optional quote. Every materialized fact should have >=1 Citation."""

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    fact = GenericForeignKey("content_type", "object_id")

    document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.CASCADE, related_name="citations"
    )
    page = models.PositiveIntegerField(null=True, blank=True)
    transcript_segment = models.ForeignKey(
        TranscriptSegment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="citations",
    )
    quote = models.TextField(blank=True)

    objects = CitationManager()

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"], name="idx_citation_fact")]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(document__isnull=False)
                | models.Q(transcript_segment__isnull=False),
                name="citation_has_evidence",
            )
        ]

    def __str__(self):
        return f"Citation({self.content_type} #{self.object_id})"
