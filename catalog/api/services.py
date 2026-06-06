"""Shared helpers for the ingest API: the BCSD entity context (one definition,
reused by both the API and the ingest_bcsd command) and the reviewed-fact guard
that protects human review work from being clobbered on re-ingest."""

from catalog.models import (
    Appearance,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Source,
    Vote,
)

JURISDICTION = {
    "slug": "bibb-county-boe",
    "name": "Bibb County Board of Education",
    "kind": Jurisdiction.Kind.SCHOOL_DISTRICT,
}
SOURCE = {"slug": "bcsd-boe-meetings", "name": "BCSD BOE Meetings", "adapter": "bcsd"}
BODY = {
    "slug": "boe",
    "name": "Bibb County Board of Education",
    "kind": Organization.Kind.COMMITTEE,
}


def bcsd_context():
    """get_or_create the BCSD Jurisdiction, Source, and Organization (body)."""
    jurisdiction, _ = Jurisdiction.objects.get_or_create(
        slug=JURISDICTION["slug"],
        defaults={"name": JURISDICTION["name"], "kind": JURISDICTION["kind"]},
    )
    source, _ = Source.objects.get_or_create(
        slug=SOURCE["slug"],
        defaults={
            "name": SOURCE["name"],
            "adapter": SOURCE["adapter"],
            "jurisdiction": jurisdiction,
        },
    )
    body, _ = Organization.objects.get_or_create(
        slug=BODY["slug"],
        jurisdiction=jurisdiction,
        defaults={"name": BODY["name"], "kind": BODY["kind"], "reviewed": True},
    )
    return jurisdiction, source, body


def meeting_has_reviewed_facts(source, source_meeting_id) -> bool:
    """True if a meeting (by natural key) already holds any reviewed=True
    Vote, Appearance, or Motion — the facts load_meeting would wipe."""
    meeting = Meeting.objects.filter(source=source, source_meeting_id=source_meeting_id).first()
    if meeting is None:
        return False
    return (
        Vote.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
        or Appearance.objects.filter(meeting=meeting, reviewed=True).exists()
        or Motion.objects.filter(agenda_item__meeting=meeting, reviewed=True).exists()
    )
