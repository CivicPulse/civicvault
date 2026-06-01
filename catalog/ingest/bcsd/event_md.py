"""Parse a BCSD event.md (brief §5.1): metadata + agenda outline + files map."""

import html
import re
from dataclasses import dataclass, field

# An agenda-item line carries a code like "IS-1", "FSS-3", "PR-4", "PS-1", "FI-1".
_CODE = re.compile(r"\b([A-Z]{2,4}-\d+)\b")
_TYPE = re.compile(r"\(([A-Z]+)(?:\s*-\s*(First|Second)\s+Reading)?\)\s*$", re.IGNORECASE)
# Leading outline prefix: "I.", "i.", "a.", "ii." etc.
_OUTLINE_PREFIX = re.compile(r"^(?:[IVXLC]+|[ivxlc]+|[a-z]|\d+)\.\s+")
# A files line: `filename` (attribution text)
_FILE_LINE = re.compile(r"^-\s*`(?P<fname>[^`]+)`\s*\((?P<attr>.*)\)\s*$")
_META_LINE = re.compile(r"^-\s*\*\*(?P<key>[^:]+):\*\*\s*(?P<val>.*)$")

_TYPE_MAP = {
    "ACTION": "action",
    "PRESENTATION": "presentation",
    "INFORMATION": "information",
}


@dataclass(frozen=True)
class EventItem:
    order: int
    code: str
    title: str
    item_type: str
    reading_stage: str
    section: str


@dataclass(frozen=True)
class ParsedEvent:
    meeting_id: str
    meeting_type: str
    source_url: str
    folder: str
    agenda_items: tuple[EventItem, ...] = ()
    files: dict[str, str] = field(default_factory=dict)


def _classify(text: str) -> tuple[str, str]:
    """Return (item_type, reading_stage) from a trailing (TYPE - Reading) marker."""
    m = _TYPE.search(text)
    if not m:
        return "other", ""
    item_type = _TYPE_MAP.get(m.group(1).upper(), "other")
    stage = (m.group(2) or "").lower()
    return item_type, stage


def parse_event_md(text: str) -> ParsedEvent:
    lines = text.splitlines()
    meta: dict[str, str] = {}
    items: list[EventItem] = []
    files: dict[str, str] = {}
    section = ""
    order = 0
    mode = "meta"

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("## Agenda Items"):
            mode = "agenda"
            continue
        if stripped.startswith("## Files"):
            mode = "files"
            continue
        if stripped.startswith("## Notes"):
            mode = "notes"
            continue

        if mode == "meta":
            mm = _META_LINE.match(stripped)
            if mm:
                meta[mm["key"].strip().lower()] = html.unescape(mm["val"].strip().strip("`"))
        elif mode == "agenda":
            if not stripped.startswith("- "):
                continue
            body = html.unescape(stripped[2:].strip())
            prefix_m = _OUTLINE_PREFIX.match(body)
            content = body[prefix_m.end() :] if prefix_m else body
            code_m = _CODE.search(content)
            # Section headers are Roman-numeral, all-caps committee names with no item code.
            is_section = bool(re.match(r"^[IVXLC]+\.\s", body)) and code_m is None
            if is_section:
                section = body
                continue
            order += 1
            code = code_m.group(1) if code_m else ""
            item_type, stage = _classify(content)
            # Title: strip a leading code token and the trailing (TYPE) marker.
            title = content
            if code:
                title = title[code_m.end() :].strip()
            title = _TYPE.sub("", title).strip()
            items.append(
                EventItem(
                    order=order,
                    code=code,
                    title=title,
                    item_type=item_type,
                    reading_stage=stage,
                    section=section,
                )
            )
        elif mode == "files":
            fm = _FILE_LINE.match(stripped)
            if fm:
                files[fm["fname"]] = html.unescape(fm["attr"].strip())

    return ParsedEvent(
        meeting_id=meta.get("meeting id", ""),
        meeting_type=meta.get("meeting type", ""),
        source_url=meta.get("source url", ""),
        folder=meta.get("folder", ""),
        agenda_items=tuple(items),
        files=files,
    )
