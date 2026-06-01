from django.contrib.postgres.fields import ArrayField
from django.db import models

from .base import Reviewable, TimeStamped


class Jurisdiction(TimeStamped):
    """A government grouping (e.g. a school district, city, county) that
    meetings, offices, and source documents belong to (brief §14.5)."""

    class Kind(models.TextChoices):
        SCHOOL_DISTRICT = "school_district", "School District"
        CITY = "city", "City"
        COUNTY = "county", "County"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Source(TimeStamped):
    """Provenance tag: which archive/adapter run a record came from (brief §14.5).
    Useful for re-ingestion, audits, and "where did this come from"."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    jurisdiction = models.ForeignKey(
        Jurisdiction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sources",
    )
    adapter = models.CharField(max_length=128, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.slug


class Organization(Reviewable):
    """Any organization: meeting body, school, vendor, nonprofit, campaign.
    Bodies are agency-scoped (jurisdiction set); vendors are cross-agency
    (jurisdiction null) so the same vendor unifies across agencies (§14.4)."""

    class Kind(models.TextChoices):
        DISTRICT = "district", "District"
        SCHOOL = "school", "School"
        COMPANY = "company", "Company (vendor)"
        NONPROFIT = "nonprofit", "Nonprofit"
        COMMITTEE = "committee", "Committee"
        CAMPAIGN = "campaign", "Campaign"
        OTHER = "other", "Other"

    name = models.CharField(max_length=255)
    aka = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    slug = models.SlugField(max_length=255)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.OTHER)
    jurisdiction = models.ForeignKey(
        Jurisdiction,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="organizations",
    )
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["jurisdiction", "slug"],
                name="uniq_org_slug_per_jurisdiction",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(jurisdiction__isnull=True),
                name="uniq_global_org_slug",
            ),
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_organization",
            ),
        ]

    def __str__(self):
        return self.name


class Person(Reviewable):
    """A canonical individual after dedup (brief §7)."""

    full_name = models.CharField(max_length=255)
    aka = ArrayField(models.CharField(max_length=255), default=list, blank=True)
    slug = models.SlugField(max_length=255, unique=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(confidence__isnull=True)
                | models.Q(confidence__gte=0, confidence__lte=1),
                name="confidence_range_person",
            )
        ]

    def __str__(self):
        return self.full_name
