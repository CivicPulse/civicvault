"""Core views for CivicVault.

`home` is the public front door: a search-first console backed by live corpus
counts. `search` is a lean, real lookup across documents and meeting-video
transcripts, with every hit traced back to its source (the provenance
principle). `health` is a machine-readable liveness endpoint.

Search uses case-insensitive `icontains` rather than the PostgreSQL
`SearchVectorField` on the models. That keeps this view portable and correct
even before search vectors are populated; ranked FTS is a later optimization
layered on top of the same UI.
"""

import re
from collections import defaultdict
from urllib.parse import urlencode

from django.core.files.storage import default_storage
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from catalog.models import (
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Person,
    TranscriptSegment,
    Vote,
)

# Curated probe queries shown as one-click chips. Chosen to land real hits in
# the seed (BCSD) corpus; each one runs an actual search, so none are dead.
SUGGESTED_QUERIES = ["budget", "contract", "policy", "superintendent"]

# Lean result caps for the unranked search. Enough to be useful; the summary
# line always reports the true total so nothing is silently hidden.
DOC_LIMIT = 25
SEGMENT_LIMIT = 25

_WS = re.compile(r"\s+")


def _initials(name, limit=4):
    """Compact letter-mark for an agency, e.g. 'Bibb County Board of Education'
    -> 'BCBE'. Skips small joining words so the mark reads cleanly."""
    skip = {"of", "the", "and", "for", "a", "an"}
    letters = [w[0] for w in name.split() if w and w.lower() not in skip]
    return "".join(letters[:limit]).upper() or name[:2].upper()


def _plural(n, singular, plural=None):
    """Pick the grammatically correct label for a count ('1 agency', '4 meetings')."""
    return singular if n == 1 else (plural or singular + "s")


def _timecode(seconds):
    """Seconds -> H:MM:SS (or M:SS under an hour). Mirrors a video scrubber."""
    total = int(seconds or 0)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _snippet(text, query, radius=130):
    """Return a short, HTML-safe excerpt around the first match of `query`,
    with each occurrence wrapped in <mark>.

    Everything is escaped before the <mark> tags are inserted, so the result is
    safe to mark_safe: the only HTML that survives is the highlight we add.
    """
    if not text:
        return ""
    text = _WS.sub(" ", text).strip()
    low, ql = text.lower(), query.lower()
    idx = low.find(ql)

    if idx == -1:
        # Matched a different field (e.g. the title). Show a leading excerpt.
        head = text[: radius * 2]
        return mark_safe(escape(head) + ("…" if len(text) > len(head) else ""))

    start = max(0, idx - radius)
    end = min(len(text), idx + len(query) + radius)
    chunk = text[start:end]

    pattern = re.compile(re.escape(query), re.IGNORECASE)
    out, last = [], 0
    for m in pattern.finditer(chunk):
        out.append(escape(chunk[last : m.start()]))
        out.append("<mark>" + escape(m.group(0)) + "</mark>")
        last = m.end()
    out.append(escape(chunk[last:]))

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return mark_safe(prefix + "".join(out) + suffix)


def home(request):
    """Public front door: live corpus readout, agencies, recent meetings."""

    # Index manifest — a terminal-style readout of what is actually indexed.
    counts = [
        (Jurisdiction.objects.count(), "agency", "agencies"),
        (Meeting.objects.count(), "meeting", None),
        (Document.objects.count(), "document", None),
        (TranscriptSegment.objects.count(), "transcript line", None),
        (Citation.objects.count(), "citation", None),
        (Motion.objects.count(), "motion", None),
        (Vote.objects.count(), "vote", None),
    ]
    stats = [{"value": n, "label": _plural(n, sing, plur)} for n, sing, plur in counts]

    # Agencies, with holdings counted both through their meetings and through
    # documents tagged to the agency's source (catches standalone policies).
    jurisdictions = []
    for j in Jurisdiction.objects.annotate(n_meetings=Count("meetings", distinct=True)):
        n_docs = (
            Document.objects.filter(
                Q(meeting__jurisdiction=j) | Q(source__jurisdiction=j)
            )
            .distinct()
            .count()
        )
        jurisdictions.append(
            {
                "name": j.name,
                "initials": _initials(j.name),
                "kind_label": j.get_kind_display(),
                "meetings": j.n_meetings,
                "documents": n_docs,
            }
        )

    # Most recent meetings, with document counts and whether video exists.
    recent_qs = (
        Meeting.objects.select_related("body")
        .annotate(
            n_docs=Count("documents", distinct=True),
            n_cov=Count("coverages", distinct=True),
        )
        .order_by("-date", "start_time")[:6]
    )
    recent_meetings = [
        {
            "date": m.date,
            "kind": m.get_kind_display(),
            "body": m.body.name if m.body_id else "",
            "documents": m.n_docs,
            "has_video": m.n_cov > 0,
        }
        for m in recent_qs
    ]

    context = {
        "stats": stats,
        "jurisdictions": jurisdictions,
        "recent_meetings": recent_meetings,
        "suggestions": SUGGESTED_QUERIES,
    }
    return render(request, "core/home.html", context)


def search(request):
    """Lean search across documents and transcript segments.

    Each transcript hit links to the exact second of the source video
    (TranscriptSegment.start is the YouTube ?t= offset), so a match in speech is
    one click from where it was said.
    """
    q = (request.GET.get("q") or "").strip()
    context = {"q": q, "suggestions": SUGGESTED_QUERIES, "nav": "search"}

    if not q:
        return render(request, "core/search.html", context)

    # ---- Documents -----------------------------------------------------
    doc_qs = Document.objects.filter(Q(title__icontains=q) | Q(text__icontains=q))
    doc_total = doc_qs.count()
    doc_hits = []
    for d in doc_qs.select_related("meeting").order_by("-meeting__date", "title")[:DOC_LIMIT]:
        # A public document is linkable if it has either an original URL or a
        # stored file; the source route (below) resolves whichever exists.
        has_source = d.access_level == Document.AccessLevel.PUBLIC and bool(
            d.source_url or d.r2_key
        )
        doc_hits.append(
            {
                "id": d.pk,
                "title": d.title,
                "kind": d.get_kind_display(),
                "has_source": has_source,
                "snippet": _snippet(d.text, q),
                "meeting_date": d.meeting.date if d.meeting_id else None,
                "meeting_kind": d.meeting.get_kind_display() if d.meeting_id else "",
            }
        )

    # ---- Transcript segments -------------------------------------------
    seg_qs = TranscriptSegment.objects.filter(text__icontains=q)
    seg_total = seg_qs.count()
    segment_hits = []
    seg_page = (
        seg_qs.select_related("transcript__media")
        .prefetch_related("transcript__media__coverages__meeting")
        .order_by("transcript", "start")[:SEGMENT_LIMIT]
    )
    for s in seg_page:
        media = s.transcript.media
        # Which meeting does this moment fall in? A recording can cover more
        # than one meeting; pick the coverage window containing this offset.
        meeting = None
        for cov in media.coverages.all():
            lo = cov.start_offset or 0
            hi = cov.end_offset
            if s.start >= lo and (hi is None or s.start < hi):
                meeting = cov.meeting
                break

        video_url = ""
        if media.youtube_id:
            video_url = f"https://www.youtube.com/watch?v={media.youtube_id}&t={int(s.start)}s"

        meeting_date = meeting.date if meeting else (media.recorded_on or media.upload_date)
        segment_hits.append(
            {
                "snippet": _snippet(s.text, q),
                "timecode": _timecode(s.start),
                "video_url": video_url,
                "context": meeting.get_kind_display() if meeting else "Meeting recording",
                "meeting_date": meeting_date,
            }
        )

    context.update(
        {
            "doc_hits": doc_hits,
            "doc_total": doc_total,
            "segment_hits": segment_hits,
            "segment_total": seg_total,
            "total": doc_total + seg_total,
        }
    )
    return render(request, "core/search.html", context)


def document_source(request, pk):
    """Redirect to a document's source: its original URL, else its stored file.

    This is the stable, shareable provenance link for a document. It hides where
    the file actually lives (an external page now, an R2 object today, a signed
    URL tomorrow) behind one address, and only ever resolves PUBLIC documents so
    restricted records can't be reached by guessing an id.
    """
    doc = get_object_or_404(Document, pk=pk, access_level=Document.AccessLevel.PUBLIC)
    if doc.source_url:
        return redirect(doc.source_url)
    if doc.r2_key:
        return redirect(default_storage.url(doc.r2_key))
    raise Http404("This document has no retrievable source.")


# Visual vocabulary for the graph, shared by the live SVG and the no-JS
# fallback list. Each entity type has a label, a node SHAPE, and an OKLCH hue —
# color is never the sole signal (DESIGN.md): shape + label always travel with it.
# Hues are spread around the wheel for color-blind separability and deliberately
# avoid Signal Cyan (215), which is reserved for the selected/active state.
GRAPH_TYPES = {
    "jurisdiction": {"label": "Jurisdiction", "shape": "hexagon", "hue": 90},
    "organization": {"label": "Body", "shape": "square", "hue": 300},
    "meeting": {"label": "Meeting", "shape": "diamond", "hue": 150},
    "person": {"label": "Person", "shape": "circle", "hue": 25},
}

# How many source documents to surface inline on a meeting node's detail rail.
GRAPH_MEETING_DOCS = 8


def _search_href(query):
    """A real search URL for an entity — the public 'follow to evidence' path."""
    return reverse("core:search") + "?" + urlencode({"q": query})


def graph(request):
    """The relationship graph: the public record as a constellation of entities.

    Renders the corpus as nodes (Jurisdiction, Body, Meeting, Person) connected by
    real relationships (a body sits in a jurisdiction, a meeting is held by a body,
    a person appeared at / voted in a meeting). Documents and agenda items are not
    nodes — at corpus scale they'd swamp the graph — so they live in a selected
    node's detail rail instead, where their source links keep provenance one click
    away (Principle 1).

    The review gate is load-bearing: Person and Organization are Reviewable, so only
    reviewed=True entities and reviewed facts (Vote/Appearance/Motion) are ever
    emitted. Nothing unverified reaches the public graph.
    """
    nodes = []
    edges = []

    # ---- Jurisdictions (always public) ---------------------------------
    for j in Jurisdiction.objects.all():
        jid = f"jurisdiction-{j.pk}"
        n_orgs = Organization.objects.filter(jurisdiction=j, reviewed=True).count()
        n_meetings = Meeting.objects.filter(jurisdiction=j).count()
        n_people = (
            Person.objects.filter(
                reviewed=True, appearances__meeting__jurisdiction=j
            )
            .distinct()
            .count()
        )
        n_docs = (
            Document.objects.filter(Q(meeting__jurisdiction=j) | Q(source__jurisdiction=j))
            .distinct()
            .count()
        )
        nodes.append(
            {
                "id": jid,
                "type": "jurisdiction",
                "label": j.name,
                "sublabel": j.get_kind_display(),
                "href": "",
                "stats": [
                    ["Bodies", n_orgs],
                    ["Meetings", n_meetings],
                    ["People", n_people],
                    ["Documents", n_docs],
                ],
                "docs": [],
            }
        )

    # ---- Bodies / organizations (reviewed only) ------------------------
    org_ids = set()
    for o in Organization.objects.filter(reviewed=True).select_related("jurisdiction"):
        oid = f"organization-{o.pk}"
        org_ids.add(o.pk)
        n_meetings = Meeting.objects.filter(body=o).count()
        n_people = (
            Person.objects.filter(reviewed=True, appearances__meeting__body=o).distinct().count()
        )
        nodes.append(
            {
                "id": oid,
                "type": "organization",
                "label": o.name,
                "sublabel": o.get_kind_display(),
                "href": _search_href(o.name),
                "stats": (
                    [["Meetings", n_meetings], ["People seen", n_people]]
                    + ([["Aliases", len(o.aka)]] if o.aka else [])
                ),
                "docs": [],
            }
        )
        if o.jurisdiction_id:
            edges.append(
                {
                    "source": oid,
                    "target": f"jurisdiction-{o.jurisdiction_id}",
                    "kind": "in",
                    "label": "sits in",
                }
            )

    # ---- Meetings (always public) --------------------------------------
    meeting_qs = Meeting.objects.select_related("body").annotate(
        n_docs=Count("documents", distinct=True),
        n_items=Count("agenda_items", distinct=True),
    )
    for m in meeting_qs:
        mid = f"meeting-{m.pk}"
        n_votes = Vote.objects.filter(reviewed=True, agenda_item__meeting=m).count()
        docs = [
            {
                "title": d.title,
                "href": (
                    reverse("core:document_source", args=[d.pk])
                    if d.access_level == Document.AccessLevel.PUBLIC and (d.source_url or d.r2_key)
                    else ""
                ),
            }
            for d in m.documents.all()[:GRAPH_MEETING_DOCS]
        ]
        nodes.append(
            {
                "id": mid,
                "type": "meeting",
                "label": f"{m.date:%b %-d, %Y}",
                "sublabel": m.get_kind_display(),
                "href": "",
                "stats": [
                    ["Agenda items", m.n_items],
                    ["Documents", m.n_docs],
                    ["Recorded votes", n_votes],
                ],
                "docs": docs,
            }
        )
        if m.body_id and m.body_id in org_ids:
            edges.append(
                {
                    "source": mid,
                    "target": f"organization-{m.body_id}",
                    "kind": "held_by",
                    "label": "held by",
                }
            )

    # ---- People (reviewed only) + their meeting ties -------------------
    # Aggregate per-person vote breakdowns and motion counts up front so each
    # person node is one dict build, not a query per node.
    vote_breakdown = defaultdict(lambda: defaultdict(int))
    for row in Vote.objects.filter(reviewed=True).values("person_id", "value"):
        vote_breakdown[row["person_id"]][row["value"]] += 1
    moved = defaultdict(int)
    for row in Motion.objects.filter(reviewed=True, moved_by__isnull=False).values("moved_by"):
        moved[row["moved_by"]] += 1
    seconded = defaultdict(int)
    for row in (
        Motion.objects.filter(reviewed=True, seconded_by__isnull=False).values("seconded_by")
    ):
        seconded[row["seconded_by"]] += 1

    # Person -> meeting ties, unioned from appearances and votes, with a weight
    # so the live layout can weight a heavier tie's spring.
    pm = defaultdict(lambda: {"votes": 0, "appeared": False})
    appearances_by_person = defaultdict(int)
    for ap in Appearance.objects.filter(reviewed=True).values("person_id", "meeting_id"):
        pm[(ap["person_id"], ap["meeting_id"])]["appeared"] = True
        appearances_by_person[ap["person_id"]] += 1
    for vt in Vote.objects.filter(reviewed=True).values("person_id", "agenda_item__meeting_id"):
        pm[(vt["person_id"], vt["agenda_item__meeting_id"])]["votes"] += 1

    person_ids = set()
    for p in Person.objects.filter(reviewed=True):
        pid = f"person-{p.pk}"
        person_ids.add(p.pk)
        vb = vote_breakdown.get(p.pk, {})
        n_votes = sum(vb.values())
        stats = [["Appearances", appearances_by_person.get(p.pk, 0)], ["Votes", n_votes]]
        if n_votes:
            tally = " · ".join(
                f"{vb[v]} {label}"
                for v, label in (("yea", "yea"), ("nay", "nay"), ("abstain", "abst"))
                if vb.get(v)
            )
            if tally:
                stats.append(["Vote tally", tally])
        if moved.get(p.pk):
            stats.append(["Motions moved", moved[p.pk]])
        if seconded.get(p.pk):
            stats.append(["Motions seconded", seconded[p.pk]])
        nodes.append(
            {
                "id": pid,
                "type": "person",
                "label": p.full_name,
                "sublabel": "",
                "href": _search_href(p.full_name),
                "stats": stats,
                "docs": [],
            }
        )

    for (person_pk, meeting_pk), tie in pm.items():
        if person_pk not in person_ids:
            continue
        if tie["votes"] and tie["appeared"]:
            label, kind, weight = f"voted ({tie['votes']})", "voted", tie["votes"]
        elif tie["votes"]:
            label, kind, weight = f"voted ({tie['votes']})", "voted", tie["votes"]
        else:
            label, kind, weight = "appeared", "appeared", 1
        edges.append(
            {
                "source": f"person-{person_pk}",
                "target": f"meeting-{meeting_pk}",
                "kind": kind,
                "label": label,
                "weight": weight,
            }
        )

    # Grouped view for the no-JS fallback list (server-rendered, accessible).
    groups = []
    for type_key, meta in GRAPH_TYPES.items():
        members = [n for n in nodes if n["type"] == type_key]
        if members:
            groups.append({"key": type_key, "meta": meta, "nodes": members})

    legend = [{"key": k, **v} for k, v in GRAPH_TYPES.items()]

    # Readable relationships for the no-JS fallback ("X held by Y"). Endpoint
    # ids + types ride along so the List view filters edges like the graph does.
    id_label = {n["id"]: n["label"] for n in nodes}
    id_type = {n["id"]: n["type"] for n in nodes}
    fallback_edges = [
        {
            "from": id_label[e["source"]],
            "rel": e["label"],
            "to": id_label[e["target"]],
            "source_type": id_type[e["source"]],
            "target_type": id_type[e["target"]],
        }
        for e in edges
    ]

    context = {
        "graph_data": {"nodes": nodes, "edges": edges},
        "graph_groups": groups,
        "fallback_edges": fallback_edges,
        "legend": legend,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "suggestions": SUGGESTED_QUERIES,
        "nav": "graph",
    }
    return render(request, "core/graph.html", context)


def health(request):
    """Liveness check: report that the process is up and serving requests.

    This deliberately does NOT touch the database. A liveness probe answers only
    "is this process alive?" — if it returns, the WSGI worker accepted a request
    and ran Python, which is all liveness needs to know. Keeping the database out
    of it means a transient Postgres blip can't make K8s restart otherwise-healthy
    pods (a DB-coupled liveness probe can cause a restart storm under DB pressure).

    Upgrade path: when we want a *readiness* probe (gate traffic on the DB being
    reachable), add a separate endpoint that runs a trivial query and returns 503
    on failure — readiness, not liveness, is the right place for that check.
    """
    return JsonResponse({"status": "ok"})
