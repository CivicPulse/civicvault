"""Generic IR -> Django loader (brief §14.3). Agency-agnostic: it never imports a
BCSD module. Writes everything as reviewed=False proposals and emits a Citation
into the minutes Document for every materialized Vote/Appearance/Motion WHEN a
minutes Document is present.

Idempotency: keyed on Meeting (source, source_meeting_id). Re-ingest wipes the
meeting's existing facts (agenda items -> motions/votes; appearances; source
documents -> citations) and recreates them. Shared entities (Jurisdiction,
Source, Organization, Person) are get_or_create and never wiped. NOTE: once admin
review begins, this wipe strategy must be revisited (out of scope for slice 1b).
"""

from django.db import IntegrityError, transaction
from django.utils.text import slugify

from catalog.ingest.ir import ParsedMeeting, ParsedPerson, ParsedRecording
from catalog.ingest.match import CoverageDecision
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Motion,
    Person,
    Transcript,
    TranscriptSegment,
    Vote,
)

_ITEM_TYPE = {
    "action": AgendaItem.ItemType.ACTION,
    "presentation": AgendaItem.ItemType.PRESENTATION,
    "information": AgendaItem.ItemType.INFORMATION,
    "other": AgendaItem.ItemType.OTHER,
}
_READING = {
    "first": AgendaItem.ReadingStage.FIRST,
    "second": AgendaItem.ReadingStage.SECOND,
    "": "",
}
_OUTCOME = {
    "passed": AgendaItem.OutcomeStatus.PASSED,
    "failed": AgendaItem.OutcomeStatus.FAILED,
    "tabled": AgendaItem.OutcomeStatus.TABLED,
    "postponed": AgendaItem.OutcomeStatus.POSTPONED,
    "unanimous": AgendaItem.OutcomeStatus.UNANIMOUS,
    "none": AgendaItem.OutcomeStatus.NONE,
}
_VOTE_VALUE = {
    "yea": Vote.Value.YEA,
    "nay": Vote.Value.NAY,
    "abstain": Vote.Value.ABSTAIN,
    "absent": Vote.Value.ABSENT,
}
_MOTION_KIND = {
    "simple": Motion.Kind.SIMPLE,
    "initial": Motion.Kind.INITIAL,
    "amended": Motion.Kind.AMENDED,
}
_MOTION_STATUS = {
    "passed": Motion.Status.PASSED,
    "failed": Motion.Status.FAILED,
    "unanimous": Motion.Status.UNANIMOUS,
    "none": Motion.Status.NONE,
}
_APPEARANCE_ROLE = {
    "member": Appearance.Role.MEMBER,
    "speaker": Appearance.Role.SPEAKER,
    "presenter": Appearance.Role.PRESENTER,
    "staff": Appearance.Role.STAFF,
    "invocation": Appearance.Role.INVOCATION,
    "pledge": Appearance.Role.PLEDGE,
}


def _meeting_slug(parsed: ParsedMeeting) -> str:
    return slugify(f"{parsed.date.isoformat()}-{parsed.kind_slug}-mid-{parsed.source_meeting_id}")


def _get_person(parsed_person: ParsedPerson, cache: dict[str, Person]) -> Person:
    slug = slugify(parsed_person.full_name) or slugify(parsed_person.raw_name)
    if not slug:
        raise ValueError(f"Could not derive a slug for person: {parsed_person!r}")
    if slug in cache:
        return cache[slug]
    person, _ = Person.objects.get_or_create(
        slug=slug, defaults={"full_name": parsed_person.full_name, "reviewed": False}
    )
    cache[slug] = person
    return person


def _doc_kind(raw: str) -> Document.Kind:
    return Document.Kind(raw) if raw in Document.Kind.values else Document.Kind.OTHER


def _ocr_status(raw: str) -> Document.OCRStatus:
    return (
        Document.OCRStatus(raw) if raw in Document.OCRStatus.values else Document.OCRStatus.UNKNOWN
    )


@transaction.atomic
def load_meeting(parsed: ParsedMeeting, *, source, jurisdiction, body) -> Meeting:
    meeting, _ = Meeting.objects.update_or_create(
        source=source,
        source_meeting_id=parsed.source_meeting_id,
        defaults={
            "body": body,
            "jurisdiction": jurisdiction,
            "date": parsed.date,
            "start_time": parsed.start_time,
            "kind": Meeting.kind_from_slug(parsed.kind_slug),
            "raw_type_slug": parsed.kind_slug,
            "title": parsed.title,
            "source_url": parsed.source_url,
            "source_path": parsed.source_path,
            "slug": _meeting_slug(parsed),
        },
    )

    # Idempotency: wipe this meeting's existing facts before recreating.
    AgendaItem.objects.filter(meeting=meeting).delete()  # cascades motions + votes
    Appearance.objects.filter(meeting=meeting).delete()
    Document.objects.filter(meeting=meeting).delete()  # cascades citations on these docs

    # Source documents (so Citations have an evidence target).
    minutes_doc = None
    for pdoc in parsed.raw_documents:
        if pdoc.is_attachment:
            continue  # attachment docs are created after agenda items exist (see below)
        doc = Document.objects.create(
            title=pdoc.title,
            kind=_doc_kind(pdoc.kind),
            meeting=meeting,
            source=source,
            source_url=parsed.source_url,
            text=pdoc.text,
            ocr_status=Document.OCRStatus.HAS_TEXT,
        )
        if pdoc.kind == "minutes":
            minutes_doc = doc

    person_cache: dict[str, Person] = {}

    # Roster -> member appearances (+ citation when we have a minutes doc).
    for rp in parsed.roster:
        person = _get_person(rp, person_cache)
        try:
            appearance = Appearance.objects.create(
                person=person, meeting=meeting, role=Appearance.Role.MEMBER, reviewed=False
            )
        except IntegrityError as exc:
            raise ValueError(
                f"Duplicate member appearance for person {person.full_name!r} "
                f"(slug {person.slug!r}) in meeting {meeting.source_meeting_id!r} — "
                f"likely a same-name Person merge or a duplicate roster entry. "
                f"Fix the parser/data before ingest."
            ) from exc
        if minutes_doc:
            Citation.objects.create(fact=appearance, document=minutes_doc)

    # Other appearances (invocation/pledge/visitors).
    for pa in parsed.appearances:
        if pa.role not in _APPEARANCE_ROLE:
            raise ValueError(f"Unknown appearance role: {pa.role!r}")
        person = _get_person(pa.person, person_cache)
        role = _APPEARANCE_ROLE[pa.role]
        try:
            appearance = Appearance.objects.create(
                person=person,
                meeting=meeting,
                role=role,
                reviewed=False,
            )
        except IntegrityError as exc:
            raise ValueError(
                f"Duplicate {pa.role!r} appearance for person {person.full_name!r} "
                f"(slug {person.slug!r}) in meeting {meeting.source_meeting_id!r} — "
                f"likely a same-name Person merge or a duplicate roster entry. "
                f"Fix the parser/data before ingest."
            ) from exc
        if minutes_doc:
            Citation.objects.create(fact=appearance, document=minutes_doc)

    # Agenda items + motions + roll-call votes.
    item_by_code: dict[str, AgendaItem] = {}
    for pitem in parsed.agenda_items:
        item = AgendaItem.objects.create(
            meeting=meeting,
            order=pitem.order,
            code=pitem.code,
            title=pitem.title,
            item_type=_ITEM_TYPE.get(pitem.item_type, AgendaItem.ItemType.OTHER),
            reading_stage=_READING.get(pitem.reading_stage, ""),
            outcome_text=pitem.outcome_text,
            outcome_status=_OUTCOME.get(pitem.outcome_status, AgendaItem.OutcomeStatus.NONE),
        )
        item_by_code[pitem.code] = item
        for pm in pitem.motions:
            motion = Motion.objects.create(
                agenda_item=item,
                kind=_MOTION_KIND.get(pm.kind, Motion.Kind.SIMPLE),
                sequence=pm.sequence,
                moved_by=_get_person(pm.moved_by, person_cache) if pm.moved_by else None,
                seconded_by=_get_person(pm.seconded_by, person_cache) if pm.seconded_by else None,
                result_text=pm.result_text,
                status=_MOTION_STATUS.get(pm.status, Motion.Status.NONE),
                reviewed=False,
            )
            if minutes_doc:
                Citation.objects.create(fact=motion, document=minutes_doc)
        for pv in pitem.votes:
            if pv.value not in _VOTE_VALUE:
                raise ValueError(f"Unknown vote value: {pv.value!r}")
            person = _get_person(pv.person, person_cache)
            try:
                vote = Vote.objects.create(
                    person=person,
                    agenda_item=item,
                    value=_VOTE_VALUE[pv.value],
                    reviewed=False,
                )
            except IntegrityError as exc:
                raise ValueError(
                    f"Duplicate vote for person {person.full_name!r} "
                    f"(slug {person.slug!r}) on agenda item {item.code!r} "
                    f"in meeting {meeting.source_meeting_id!r} — "
                    f"likely a same-name Person merge or a double roll-call. "
                    f"Fix the parser/data before ingest."
                ) from exc
            if minutes_doc:
                Citation.objects.create(fact=vote, document=minutes_doc)

    # Attachment Documents (created after agenda items so the FK can resolve).
    # The FTS search_vector is populated by a DB trigger (migration in a later task).
    for pdoc in parsed.raw_documents:
        if not pdoc.is_attachment:
            continue
        Document.objects.create(
            title=pdoc.title,
            kind=_doc_kind(pdoc.kind),
            meeting=meeting,
            # `or None` so an empty code never mis-links to a code-less item's "" key.
            agenda_item=item_by_code.get(pdoc.agenda_item_code or None),
            source=source,
            # source_url intentionally omitted; r2_key is the canonical reference.
            r2_key=pdoc.r2_key,
            text=pdoc.text,
            ocr_status=_ocr_status(pdoc.ocr_status),
        )

    return meeting


_TRANSCRIPT_ORIGIN = {
    "youtube_captions": Transcript.Origin.YOUTUBE_CAPTIONS,
    "whisper": Transcript.Origin.WHISPER,
}


@transaction.atomic
def load_recording(
    parsed: ParsedRecording, decisions: list[CoverageDecision], *, source
) -> MediaAsset:
    """Persist a recording as evidence: MediaAsset + Transcript + TranscriptSegments
    + MeetingCoverage. No Citations (recordings assert no facts). Idempotent on
    youtube_id: re-ingest wipes the asset's transcripts (cascades segments) and its
    coverage rows, then recreates them."""
    media, _ = MediaAsset.objects.update_or_create(
        youtube_id=parsed.youtube_id,
        defaults={
            "kind": MediaAsset.Kind.VIDEO,
            "r2_key": parsed.r2_key,
            "source_url": parsed.source_url,
            "recorded_on": parsed.recorded_on,
            "upload_date": parsed.upload_date,
            "duration_seconds": parsed.duration_seconds,
            "source": source,
        },
    )

    # Idempotency: wipe transcripts (cascades segments) + coverage before recreating.
    media.transcripts.all().delete()
    media.coverages.all().delete()

    if parsed.segments:
        if parsed.transcript_origin not in _TRANSCRIPT_ORIGIN:
            raise ValueError(f"Unknown transcript origin: {parsed.transcript_origin!r}")
        transcript = Transcript.objects.create(
            media=media,
            language="en",
            origin=_TRANSCRIPT_ORIGIN[parsed.transcript_origin],
        )
        TranscriptSegment.objects.bulk_create(
            [
                TranscriptSegment(transcript=transcript, start=s.start, end=s.end, text=s.text)
                for s in parsed.segments
            ]
        )

    for d in decisions:
        meeting = Meeting.objects.filter(pk=d.meeting_id).first()
        if meeting is None:
            raise ValueError(
                f"Coverage decision references no Meeting (pk={d.meeting_id}) for "
                f"recording {parsed.youtube_id!r}."
            )
        MeetingCoverage.objects.create(
            media=media,
            meeting=meeting,
            start_offset=d.start_offset,
            end_offset=d.end_offset,
            split_confirmed=d.split_confirmed,
        )

    return media
