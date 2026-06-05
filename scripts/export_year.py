"""Export a single year's connected subgraph from the catalog as a Django
fixture (natural foreign keys), for loading into another environment.

Read-only on the source DB. Usage:
    DATABASE_URL=<source> uv run python scripts/export_year.py 2025 /tmp/export_2025.json

Dimension tables (Jurisdiction, Source, Organization, Person) are exported in
full — they're small and shared across years; bringing them all avoids gaps and
is harmless. Year scoping applies to Meetings and everything hanging off them.
Relationship (graph edge) rows are NOT exported — they're re-derived on the
target via `build_relationships` so derivation is uniform across all years.
"""

import json
import os
import sys

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civicvault.settings")
django.setup()

from django.core import serializers  # noqa: E402
from django.db.models import Q  # noqa: E402

from catalog.models import (  # noqa: E402
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Motion,
    Organization,
    Person,
    Source,
    Transcript,
    TranscriptSegment,
    Vote,
)


def collect(year):
    meetings = Meeting.objects.filter(date__year=year).order_by("id")
    mids = list(meetings.values_list("id", flat=True))
    agenda = AgendaItem.objects.filter(meeting_id__in=mids).order_by("id")
    aids = list(agenda.values_list("id", flat=True))
    coverages = MeetingCoverage.objects.filter(meeting_id__in=mids).order_by("id")
    docs = Document.objects.filter(Q(meeting_id__in=mids) | Q(agenda_item_id__in=aids)).order_by(
        "id"
    )
    media_ids = {m for m in docs.values_list("media_id", flat=True) if m} | {
        m for m in coverages.values_list("media_id", flat=True) if m
    }
    media = MediaAsset.objects.filter(id__in=media_ids).order_by("id")
    transcripts = Transcript.objects.filter(media_id__in=media_ids).order_by("id")
    tids = list(transcripts.values_list("id", flat=True))
    segments = TranscriptSegment.objects.filter(transcript_id__in=tids).order_by("id")
    sids = list(segments.values_list("id", flat=True))
    votes = Vote.objects.filter(agenda_item_id__in=aids).order_by("id")
    appearances = Appearance.objects.filter(meeting_id__in=mids).order_by("id")
    motions = Motion.objects.filter(agenda_item_id__in=aids).order_by("id")
    citations = Citation.objects.filter(
        Q(document_id__in=list(docs.values_list("id", flat=True)))
        | Q(transcript_segment_id__in=sids)
    ).order_by("id")

    # Parents first so a plain loaddata satisfies FKs even without deferral.
    groups = [
        ("Jurisdiction", Jurisdiction.objects.all().order_by("id")),
        ("Source", Source.objects.all().order_by("id")),
        ("Organization", Organization.objects.all().order_by("id")),
        ("Person", Person.objects.all().order_by("id")),
        ("MediaAsset", media),
        ("Transcript", transcripts),
        ("TranscriptSegment", segments),
        ("Meeting", meetings),
        ("AgendaItem", agenda),
        ("MeetingCoverage", coverages),
        ("Document", docs),
        ("Vote", votes),
        ("Appearance", appearances),
        ("Motion", motions),
        ("Citation", citations),
        # Relationship rows are intentionally NOT exported — graph edges are
        # re-derived on the target via `build_relationships` after all years are
        # loaded, so derivation is uniform across copied + freshly-ingested data.
    ]
    return groups


def main():
    year = int(sys.argv[1])
    out = sys.argv[2]
    groups = collect(year)
    objects = []
    print(f"=== {year} subgraph row counts ===")
    for name, qs in groups:
        rows = list(qs)
        objects.extend(rows)
        print(f"  {name:18} {len(rows)}")
    data = serializers.serialize(
        "json", objects, use_natural_foreign_keys=True, use_natural_primary_keys=True
    )
    # Strip trigger-managed tsvector columns so loaddata doesn't fight the
    # search_vector insert/update triggers on the target.
    payload = json.loads(data)
    for obj in payload:
        obj["fields"].pop("search_vector", None)
    with open(out, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"total objects: {len(objects)}  ->  {out}")


if __name__ == "__main__":
    main()
