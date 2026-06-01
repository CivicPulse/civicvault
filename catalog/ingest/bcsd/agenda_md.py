"""Parse a BCSD agenda.md outline (brief §5.3) — fallback when minutes are absent.

The `## Agenda` section uses Markdown headers: `### <Roman>. <SECTION>` and
`#### <numeral>. <CODE> <Title> (<TYPE>)`, identical to the agenda echo at the
top of minutes.md. Reuses the event.md classification helpers."""

import html
import re

from catalog.ingest.bcsd.event_md import _CODE, EventItem, _classify

_ITEM = re.compile(r"^####\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
_SECTION = re.compile(r"^###\s+(?P<rest>[IVXLC]+\.\s+.+?)\s*$")


def parse_agenda_md(text: str) -> list[EventItem]:
    items: list[EventItem] = []
    section = ""
    order = 0
    in_agenda = False
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith("## Agenda"):
            in_agenda = True
            continue
        if s.startswith("## Meeting Minutes"):
            break
        if not in_agenda:
            continue
        sec_m = _SECTION.match(s)
        item_m = _ITEM.match(s)
        if sec_m and not _CODE.search(sec_m["rest"]):
            section = html.unescape(sec_m["rest"])
            continue
        if item_m:
            rest = html.unescape(item_m["rest"])
            code_m = _CODE.search(rest)
            code = code_m.group(1) if code_m else ""
            item_type, stage = _classify(rest)
            title = rest[code_m.end() :].strip() if code else rest
            title = re.sub(r"\s*\([A-Z].*\)\s*$", "", title).strip()
            order += 1
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
    return items
