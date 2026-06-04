"""Derive citation-backed Relationship rows from the existing corpus.

Two predicates we can prove from what is already ingested:

  * board_member_of — a Person who appears as a *member* of a body (from reviewed
    Appearance rows) is a board member of it; cited to that meeting's minutes.
  * contracts_with — a body's contract/renewal agenda items name a vendor; the
    body contracts with that vendor, with the dollar amount lifted from the item's
    outcome text and cited to the meeting's document.

Conservative by design (only clean vendor-name patterns), so it never invents an
entity it can't point at a source for. Idempotent: it owns a `derived-relationships`
Source and replaces only those rows on each run. Rows are proposals (reviewed=False)
unless --review is passed (dev convenience to make them visible in the graph).
"""

import re

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Organization,
    Person,
    Relationship,
    Source,
)

DERIVED_SOURCE = {
    "slug": "derived-relationships",
    "name": "Derived relationships",
    "adapter": "derive",
}

# Tight patterns that yield a clean vendor/service name. Anything starting with
# "Approval of" or carrying "Bid" is a process item, not a named vendor — skipped.
VENDOR_PATTERNS = [
    re.compile(r"^Renewal of (.+)$", re.I),
    re.compile(r"^FY\s*\d+\s+Renewal of (.+)$", re.I),
    re.compile(r"^(.+?)\s*[-–]\s*FY\s*\d*\s*Renewal$", re.I),
    re.compile(r"^(.+?)\s*[-–]\s*Contract$", re.I),
]


def vendor_name(title):
    """Pull a clean vendor name from a contract/renewal agenda title, or None."""
    title = (title or "").strip()
    if re.match(r"^approval\b", title, re.I) or re.search(r"\bbid\b", title, re.I):
        return None
    for pat in VENDOR_PATTERNS:
        m = pat.match(title)
        if m:
            name = re.sub(r"\s*[-–]\s*Contract$", "", m.group(1), flags=re.I).strip(" .,-–")
            if 2 < len(name) < 60 and not name.lower().startswith(("fy ", "fy2")):
                return name
    return None


def meeting_doc(meeting):
    """The document that best evidences a meeting: minutes, then agenda, then any."""
    qs = meeting.documents.all()
    for kind in ("minutes", "agenda"):
        d = qs.filter(kind=kind).first()
        if d:
            return d
    return qs.first()


class Command(BaseCommand):
    help = "Derive board-member and vendor-contract Relationships (cited) from the corpus."

    def add_arguments(self, parser):
        parser.add_argument(
            "--review",
            action="store_true",
            help="Mark derived rows (and vendor orgs) reviewed=True so they appear in the graph.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        review = options["review"]
        src, _ = Source.objects.get_or_create(
            slug=DERIVED_SOURCE["slug"],
            defaults={"name": DERIVED_SOURCE["name"], "adapter": DERIVED_SOURCE["adapter"]},
        )
        rel_ct = ContentType.objects.get_for_model(Relationship)
        person_ct = ContentType.objects.get_for_model(Person)
        org_ct = ContentType.objects.get_for_model(Organization)

        # Idempotent rebuild: drop this source's prior rows and their citations.
        old_ids = list(Relationship.objects.filter(source=src).values_list("pk", flat=True))
        Citation.objects.filter(content_type=rel_ct, object_id__in=old_ids).delete()
        Relationship.objects.filter(source=src).delete()

        def cite(rel, doc, quote):
            if doc:
                Citation.objects.create(
                    content_type=rel_ct, object_id=rel.pk, document=doc, quote=quote[:500]
                )

        # ---- board_member_of -------------------------------------------------
        members = 0
        seen = set()
        appearances = (
            Appearance.objects.filter(reviewed=True, role=Appearance.Role.MEMBER)
            .select_related("person", "meeting", "meeting__body")
            .order_by("-meeting__date")
        )
        for ap in appearances:
            body = ap.meeting.body
            if not (ap.person.reviewed and body and body.reviewed):
                continue
            key = (ap.person_id, body.pk)
            if key in seen:
                continue
            seen.add(key)
            rel = Relationship.objects.create(
                subject_ct=person_ct,
                subject_id=ap.person_id,
                object_ct=org_ct,
                object_id=body.pk,
                predicate=Relationship.Predicate.BOARD_MEMBER_OF,
                role="member",
                source=src,
                reviewed=review,
            )
            cite(rel, meeting_doc(ap.meeting), f"Appeared as a member, {ap.meeting.date}.")
            members += 1

        # ---- contracts_with --------------------------------------------------
        contracts = 0
        for item in AgendaItem.objects.select_related("meeting", "meeting__body"):
            name = vendor_name(item.title)
            body = item.meeting.body
            if not name or not (body and body.reviewed):
                continue
            vendor, _ = Organization.objects.get_or_create(
                slug=slugify(name)[:255],
                jurisdiction=None,  # vendors are cross-agency by design
                defaults={
                    "name": name,
                    "kind": Organization.Kind.COMPANY,
                    "reviewed": review,
                },
            )
            rel = Relationship.objects.create(
                subject_ct=org_ct,
                subject_id=body.pk,
                object_ct=org_ct,
                object_id=vendor.pk,
                predicate=Relationship.Predicate.CONTRACTS_WITH,
                amount=item.amount,
                occurred_on=item.meeting.date,
                note=item.title,
                source=src,
                reviewed=review,
            )
            cite(rel, meeting_doc(item.meeting), item.title)
            contracts += 1

        state = "reviewed" if review else "reviewed=False proposals"
        self.stdout.write(
            self.style.SUCCESS(
                f"Derived {members} board-member and {contracts} vendor-contract "
                f"relationships ({state})."
            )
        )
