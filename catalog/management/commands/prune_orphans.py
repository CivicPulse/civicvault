"""Delete edge-less proposal nodes left behind by re-ingestion or relationship
rebuilds: Persons with no facts/relationships, and vendor-kind Organizations with
no relationships or meetings. Dry-run by default; pass --apply to delete.

Only entities with ZERO connecting facts are eligible, so deletion strands nothing
(no citations, no edges). Bodies, schools, and jurisdiction-scoped orgs are never
considered — only the cross-agency vendor kinds.
"""

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Organization, Person, Relationship

VENDOR_KINDS = (
    Organization.Kind.COMPANY,
    Organization.Kind.NONPROFIT,
    Organization.Kind.CAMPAIGN,
)


def _related_ids(content_type):
    """Set of object PKs referenced by any Relationship as subject or object."""
    subj = Relationship.objects.filter(subject_ct=content_type).values_list("subject_id", flat=True)
    obj = Relationship.objects.filter(object_ct=content_type).values_list("object_id", flat=True)
    return set(subj) | set(obj)


def orphan_persons():
    person_ct = ContentType.objects.get_for_model(Person)
    in_rel = _related_ids(person_ct)
    # Four .exists() queries per person — O(n) at catalog scale; acceptable today.
    # Switch to .annotate(Count(...)) if Person rows grow beyond ~10k.
    return [
        p
        for p in Person.objects.all()
        if p.pk not in in_rel
        and not p.appearances.exists()
        and not p.votes.exists()
        and not p.motions_moved.exists()
        and not p.motions_seconded.exists()
    ]


def orphan_vendor_orgs():
    org_ct = ContentType.objects.get_for_model(Organization)
    in_rel = _related_ids(org_ct)
    return [
        o
        for o in Organization.objects.filter(kind__in=VENDOR_KINDS)
        if o.pk not in in_rel and not o.meetings.exists()
    ]


class Command(BaseCommand):
    help = "Delete edge-less proposal Persons and vendor Organizations (dry-run unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete the orphans (default: dry-run, only report).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        persons = orphan_persons()
        orgs = orphan_vendor_orgs()
        mode = "DELETING" if options["apply"] else "WOULD DELETE"
        for p in persons:
            self.stdout.write(f"  [{mode}] person  {p.full_name!r}")
        for o in orgs:
            self.stdout.write(f"  [{mode}] vendor  {o.name!r}")
        if options["apply"]:
            for p in persons:
                p.delete()
            for o in orgs:
                o.delete()
            self.stdout.write(
                self.style.SUCCESS(f"Deleted {len(persons)} persons and {len(orgs)} vendor orgs.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: would delete {len(persons)} persons and {len(orgs)} vendor orgs. "
                    f"Pass --apply to delete."
                )
            )
