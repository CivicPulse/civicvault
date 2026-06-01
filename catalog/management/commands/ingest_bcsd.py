"""Ingest one BCSD meeting folder (Source A) into the catalog as proposals."""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.ingest.bcsd.adapter import parse_meeting_folder
from catalog.ingest.loader import load_meeting
from catalog.models import Jurisdiction, Organization, Source

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


class Command(BaseCommand):
    help = "Ingest a BCSD meeting folder (Source A) into the catalog as reviewed=False proposals."

    def add_arguments(self, parser):
        parser.add_argument("folder", help="Path to a single meeting folder.")

    def handle(self, *args, **options):
        folder = Path(options["folder"])
        if not folder.is_dir():
            raise CommandError(f"Not a directory: {folder}")

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

        parsed = parse_meeting_folder(folder)
        meeting = load_meeting(parsed, source=source, jurisdiction=jurisdiction, body=body)
        self.stdout.write(
            self.style.SUCCESS(
                f"Ingested {meeting} (mid={meeting.source_meeting_id}): "
                f"{meeting.agenda_items.count()} items, "
                f"{sum(i.votes.count() for i in meeting.agenda_items.all())} votes, "
                f"{meeting.appearances.count()} appearances (all reviewed=False)."
            )
        )
