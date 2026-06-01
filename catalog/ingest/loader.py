"""Generic IR -> Django loader (brief §14.3). Agency-agnostic: it never imports a
BCSD module. Writes everything as reviewed=False proposals and emits a Citation
into the minutes Document for every materialized Vote/Appearance/Motion.

Idempotency: keyed on Meeting (source, source_meeting_id). Re-ingest wipes the
meeting's existing facts (agenda items -> motions/votes; appearances; source
documents -> citations) and recreates them. Shared entities (Jurisdiction,
Source, Organization, Person) are get_or_create and never wiped. NOTE: once admin
review begins, this wipe strategy must be revisited (out of scope for slice 1b).
"""

from django.db import transaction
from django.utils.text import slugify

from catalog.ingest.ir import ParsedMeeting, ParsedPerson
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Meeting,
    Motion,
    Person,
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
    if slug in cache:
        return cache[slug]
    person, _ = Person.objects.get_or_create(
        slug=slug, defaults={"full_name": parsed_person.full_name, "reviewed": False}
    )
    cache[slug] = person
    return person


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
        kind = {"minutes": Document.Kind.MINUTES, "agenda": Document.Kind.AGENDA}.get(
            pdoc.kind, Document.Kind.OTHER
        )
        doc = Document.objects.create(
            title=pdoc.title,
            kind=kind,
            meeting=meeting,
            source=source,
            source_url=parsed.source_url,
            ocr_status=Document.OCRStatus.HAS_TEXT,
        )
        if pdoc.kind == "minutes":
            minutes_doc = doc

    person_cache: dict[str, Person] = {}

    # Roster -> member appearances (+ citation when we have a minutes doc).
    for rp in parsed.roster:
        person = _get_person(rp, person_cache)
        appearance = Appearance.objects.create(
            person=person, meeting=meeting, role=Appearance.Role.MEMBER, reviewed=False
        )
        if minutes_doc:
            Citation.objects.create(fact=appearance, document=minutes_doc)

    # Other appearances (invocation/pledge/visitors).
    for pa in parsed.appearances:
        person = _get_person(pa.person, person_cache)
        appearance = Appearance.objects.create(
            person=person,
            meeting=meeting,
            role=_APPEARANCE_ROLE.get(pa.role, Appearance.Role.SPEAKER),
            reviewed=False,
        )
        if minutes_doc:
            Citation.objects.create(fact=appearance, document=minutes_doc)

    # Agenda items + motions + roll-call votes.
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
            person = _get_person(pv.person, person_cache)
            vote = Vote.objects.create(
                person=person,
                agenda_item=item,
                value=_VOTE_VALUE.get(pv.value, Vote.Value.YEA),
                reviewed=False,
            )
            if minutes_doc:
                Citation.objects.create(fact=vote, document=minutes_doc)

    return meeting
