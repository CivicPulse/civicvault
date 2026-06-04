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

from django.core.files.storage import default_storage
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.html import escape
from django.utils.safestring import mark_safe

from catalog.models import (
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Motion,
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
    context = {"q": q, "suggestions": SUGGESTED_QUERIES}

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
