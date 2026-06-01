"""BCSD Source-A adapter: a meeting folder -> one ParsedMeeting IR (brief §4-§5)."""

import re
from pathlib import Path

from catalog.ingest.bcsd.agenda_md import parse_agenda_md
from catalog.ingest.bcsd.event_md import parse_event_md
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

    items: list[ParsedAgendaItem] = []
    for ev in event_items:
        outcome = None
        if minutes is not None:
            # Code-less items are keyed by title, so two code-less items sharing
            # a title would shadow each other in minutes.outcomes (a known,
            # low-risk limitation for the current BCSD data).
            outcome = minutes.outcomes.get(ev.code) or minutes.outcomes.get(ev.title)
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
                file_names=_files_for_item(event.files, ev.code, ev.title),
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
