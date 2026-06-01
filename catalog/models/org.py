from django.db import models

from .base import TimeStamped


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
