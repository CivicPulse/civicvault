from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from .base import TimeStamped
from .media import MediaAsset
from .meeting import AgendaItem, Meeting
from .org import Source


class Document(TimeStamped):
    """A document with extracted text for full-text search (brief §7).
    May link to a Meeting and/or AgendaItem, or stand alone (policies, reports)."""

    class Kind(models.TextChoices):
        MINUTES = "minutes", "Minutes"
        AGENDA = "agenda", "Agenda"
        POLICY = "policy", "Policy"
        CONTRACT = "contract", "Contract"
        MEMO = "memo", "Memo"
        PRESENTATION = "presentation", "Presentation"
        REPORT = "report", "Report"
        ARTICLE = "article", "Article"
        OTHER = "other", "Other"

    class OCRStatus(models.TextChoices):
        HAS_TEXT = "has_text", "Has Text Layer"
        OCR_NEEDED = "ocr_needed", "OCR Needed"
        EMPTY = "empty", "Empty"
        UNKNOWN = "unknown", "Unknown"

    class AccessLevel(models.TextChoices):
        PUBLIC = "public", "Public"
        RESTRICTED = "restricted", "Restricted"

    title = models.CharField(max_length=512)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    meeting = models.ForeignKey(
        Meeting, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    agenda_item = models.ForeignKey(
        AgendaItem, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    media = models.ForeignKey(
        MediaAsset, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="documents"
    )
    r2_key = models.CharField(max_length=1024, blank=True)
    source_url = models.URLField(max_length=1024, blank=True)
    og_metadata = models.JSONField(default=dict, blank=True)
    text = models.TextField(blank=True)
    ocr_status = models.CharField(
        max_length=16, choices=OCRStatus.choices, default=OCRStatus.UNKNOWN
    )
    access_level = models.CharField(
        max_length=16, choices=AccessLevel.choices, default=AccessLevel.PUBLIC
    )
    search_vector = SearchVectorField(null=True, editable=False)

    class Meta:
        indexes = [GinIndex(fields=["search_vector"], name="gin_document_search")]
        constraints = [
            models.UniqueConstraint(
                fields=["r2_key"], condition=~models.Q(r2_key=""), name="uniq_document_r2_key"
            )
        ]

    def __str__(self):
        return self.title
