from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .base import Reviewable
from .org import Source


class Relationship(Reviewable):
    """A directed, typed, citation-backed tie between two entities — the backbone
    of the influence graph (board member of, contracts with, owns, donates to).

    Unlike the meeting-scoped facts (Vote/Appearance/Motion), a Relationship is a
    *standing* affiliation or transaction. Both ends are GenericForeignKeys so the
    same model carries person->body, body->vendor, and (later) org->org ownership
    and donation ties. Each is a reviewed proposal and should carry >=1 Citation
    (provenance is the product); the `source` tags the derivation/adapter run so a
    rebuild can replace its own rows idempotently.
    """

    class Predicate(models.TextChoices):
        BOARD_MEMBER_OF = "board_member_of", "Board member of"
        EMPLOYED_AS = "employed_as", "Employed as"
        OWNS = "owns", "Owns"
        CONTRACTS_WITH = "contracts_with", "Contracts with"
        DONATES_TO = "donates_to", "Donates to"
        AFFILIATED_WITH = "affiliated_with", "Affiliated with"

    subject_ct = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, related_name="+"
    )
    subject_id = models.PositiveBigIntegerField()
    subject = GenericForeignKey("subject_ct", "subject_id")

    object_ct = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()
    object = GenericForeignKey("object_ct", "object_id")

    predicate = models.CharField(max_length=32, choices=Predicate.choices)
    role = models.CharField(max_length=128, blank=True)  # e.g. "CEO", "member"
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    occurred_on = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)
    source = models.ForeignKey(
        Source, null=True, blank=True, on_delete=models.SET_NULL, related_name="relationships"
    )

    class Meta:
        indexes = [
            models.Index(fields=["subject_ct", "subject_id"], name="idx_rel_subject"),
            models.Index(fields=["object_ct", "object_id"], name="idx_rel_object"),
            models.Index(fields=["predicate"], name="idx_rel_predicate"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_relationship",
            ),
        ]

    def __str__(self):
        return f"{self.subject} {self.get_predicate_display()} {self.object}"
