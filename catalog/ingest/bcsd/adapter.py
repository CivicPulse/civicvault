"""BCSD Source-A adapter: a meeting folder -> one ParsedMeeting IR (brief §4-§5)."""

import re
from pathlib import Path

from catalog.ingest.bcsd.agenda_md import parse_agenda_md
from catalog.ingest.bcsd.event_md import parse_event_md
from catalog.ingest.bcsd.files import (
    document_kind_for,
    extract_pdf_text,
    r2_key_for,
    title_for,
)
from catalog.ingest.bcsd.foldername import parse_folder_name
from catalog.ingest.bcsd.minutes_md import parse_minutes_md
from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedDocument,
    ParsedMeeting,
)


def _files_for_item(files: dict[str, str], code: str, title: str) -> tuple[str, ...]:
    """Filenames whose attribution text references this item's code or title."""
    out = []
    needle = code or title
    if not needle:
        return ()
    # Word-boundary match so "FSS-1" does not also match "FSS-10"/"FSS-11"
    # (the trailing digit is a word char). re.escape keeps title needles
    # (which may contain dashes/parens) literal.
    pattern = re.compile(rf"\b{re.escape(needle)}\b")
    for fname, attr in files.items():
        if pattern.search(attr):
            out.append(fname)
    return tuple(out)


_TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def _without_classifier(title: str) -> str:
    """Drop a single trailing parenthetical classifier — e.g. '(ACTION)',
    '(BOE Action Item)', '(PRESENTATION & ACTION)', '(s)'. The minutes and event
    parsers strip these by different rules, so the same item can carry one on one
    side but not the other; canonicalizing both sides lets a code-less item still
    join its outcome instead of silently dropping its votes. (The minutes parser
    strips only uppercase-initial classifiers via its own regex; this strips any
    trailing parenthetical, which is why a fallback is needed.)"""
    return _TRAILING_PAREN.sub("", title).strip()


def parse_meeting_folder(folder: Path) -> ParsedMeeting:
    folder = Path(folder)
    fn = parse_folder_name(folder.name)
    event_text = (folder / "event.md").read_text(encoding="utf-8")
    event = parse_event_md(event_text)

    minutes_path = folder / "minutes.md"
    agenda_path = folder / "agenda.md"
    has_minutes = minutes_path.exists()
    agenda_text = agenda_path.read_text(encoding="utf-8") if agenda_path.exists() else None

    raw_documents = [
        ParsedDocument(
            kind="other", title="event.md", source_path=str(folder / "event.md"), text=event_text
        ),
    ]

    if has_minutes:
        minutes_text = minutes_path.read_text(encoding="utf-8")
        minutes = parse_minutes_md(minutes_text)
        event_items = event.agenda_items
        roster = minutes.roster
        appearances = minutes.appearances
        raw_documents.append(
            ParsedDocument(
                kind="minutes",
                title="minutes.md",
                source_path=str(minutes_path),
                text=minutes_text,
            )
        )
    else:
        if agenda_text is not None:
            event_items = tuple(parse_agenda_md(agenda_text))
        else:
            event_items = event.agenda_items
        minutes = None
        roster = ()
        appearances = ()

    if agenda_text is not None:
        raw_documents.append(
            ParsedDocument(
                kind="agenda",
                title="agenda.md",
                source_path=str(agenda_path),
                text=agenda_text,
            )
        )

    # Fallback join index: outcomes keyed by their title with a trailing
    # parenthetical classifier removed. Built only for keys whose stripped form
    # is unambiguous on BOTH sides — a stripped key shared by two outcomes is
    # excluded here, and (below) the fallback is skipped when two event items
    # share a stripped title — so a single outcome is never attached to the wrong
    # item or to two items at once.
    stripped_outcomes = {}
    event_stripped_counts: dict[str, int] = {}
    if minutes is not None:
        stripped_counts: dict[str, int] = {}
        for key in minutes.outcomes:
            sk = _without_classifier(key)
            stripped_counts[sk] = stripped_counts.get(sk, 0) + 1
        stripped_outcomes = {
            _without_classifier(key): oc
            for key, oc in minutes.outcomes.items()
            if stripped_counts[_without_classifier(key)] == 1
        }
        for ev in event_items:
            esk = _without_classifier(ev.title)
            event_stripped_counts[esk] = event_stripped_counts.get(esk, 0) + 1

    items: list[ParsedAgendaItem] = []
    for ev in event_items:
        outcome = None
        if minutes is not None:
            # Exact join by code, then by title; finally a classifier-stripped
            # fallback (the minutes/event parsers strip trailing "(...)" markers
            # inconsistently). Two code-less items sharing a title still shadow
            # each other (a known, low-risk limitation for the current BCSD data).
            base = _without_classifier(ev.title)
            fallback = stripped_outcomes.get(base) if event_stripped_counts.get(base) == 1 else None
            outcome = minutes.outcomes.get(ev.code) or minutes.outcomes.get(ev.title) or fallback
        items.append(
            ParsedAgendaItem(
                order=ev.order,
                code=ev.code,
                title=ev.title,
                item_type=ev.item_type,
                reading_stage=ev.reading_stage,
                section=ev.section,
                outcome_text=outcome.outcome_text if outcome else "",
                outcome_status=outcome.outcome_status if outcome else "none",
                motions=outcome.motions if outcome else (),
                votes=outcome.votes if outcome else (),
                amount=outcome.amount if outcome else None,
                amount_text=outcome.amount_text if outcome else "",
                file_names=_files_for_item(event.files, ev.code, ev.title),
            )
        )

    # Attachments: invert the per-item file map (filename -> item code), then walk files/.
    # Only coded items own attachment linkage; code-less procedural sections fall through
    # to meeting-level (agenda_item_code=None).
    code_by_file: dict[str, str] = {}
    for item in items:
        if not item.code:
            continue
        for fname in item.file_names:
            code_by_file.setdefault(fname, item.code)

    files_dir = folder / "files"
    if files_dir.is_dir():
        # r2_key_for() requires a BCSD_* ancestor in the path and raises ValueError
        # otherwise — fail loud rather than persist an un-keyable attachment.
        for path in sorted(p for p in files_dir.iterdir() if p.is_file()):
            text, ocr_status = ("", "unknown")
            if path.suffix.lower() == ".pdf":
                text, ocr_status = extract_pdf_text(path)
            raw_documents.append(
                ParsedDocument(
                    kind=document_kind_for(path.name),
                    title=title_for(path.name),
                    source_path=str(path),
                    text=text,
                    r2_key=r2_key_for(path),
                    ocr_status=ocr_status,
                    agenda_item_code=code_by_file.get(path.name),
                    is_attachment=True,
                )
            )

    return ParsedMeeting(
        date=fn.date,
        start_time=fn.start_time,
        kind_slug=fn.type_slug,
        source_meeting_id=fn.meeting_id or event.meeting_id,
        source_url=event.source_url,
        source_path=str(folder),
        folder_name=folder.name,
        title=event.meeting_type or folder.name,
        roster=tuple(roster),
        agenda_items=tuple(items),
        appearances=tuple(appearances),
        has_minutes=has_minutes,
        raw_documents=tuple(raw_documents),
    )
