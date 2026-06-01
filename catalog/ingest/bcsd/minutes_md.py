"""Parse a BCSD minutes.md (brief §5.2): roster, per-item outcomes, appearances."""

import html
import re
from dataclasses import dataclass, field

from catalog.ingest.bcsd.motions import parse_outcome_block
from catalog.ingest.ir import ParsedAppearance, ParsedMotion, ParsedPerson, ParsedVote
from catalog.ingest.names import normalize_name, split_name_and_role

_CODE = re.compile(r"\b([A-Z]{2,4}-\d+)\b")
_ITEM_HEADER = re.compile(r"^####\s+(?:[ivxlc]+|[a-z]|\d+)\.\s+(?P<rest>.+?)\s*$")
_SECTION_HEADER = re.compile(r"^###\s+(?P<rest>.+?)\s*$")
_INVOCATION = re.compile(r"invocation was given by\s+(?P<name>.+?)\.?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class ItemOutcome:
    code: str
    title: str
    outcome_text: str
    outcome_status: str
    motions: tuple[ParsedMotion, ...]
    votes: tuple[ParsedVote, ...]


@dataclass(frozen=True)
class ParsedMinutes:
    roster: tuple[ParsedPerson, ...] = ()
    outcomes: dict[str, ItemOutcome] = field(default_factory=dict)
    appearances: tuple[ParsedAppearance, ...] = ()


def _derive_status(outcome_text: str, motions: list[ParsedMotion]) -> str:
    """Derive item-level outcome status.  Postpone/table checks run before pass/fail."""
    low = outcome_text.lower()
    if "postpone" in low:
        return "postponed"
    if "tabled" in low or "table the" in low:
        return "tabled"
    if motions:
        if any(m.status == "unanimous" for m in motions):
            return "unanimous"
        if any(m.status == "failed" for m in motions):
            return "failed"
        return "passed"
    return "none"


def _split_meeting_minutes(text: str) -> list[str]:
    """Return the lines of the `## Meeting Minutes` section (after the agenda echo)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("## Meeting Minutes"):
            return lines[i + 1 :]
    return lines


def _parse_roster(body: list[str]) -> list[ParsedPerson]:
    roster: list[ParsedPerson] = []
    in_voting = False
    for line in body:
        s = line.strip()
        if s.startswith("#### Voting Members"):
            in_voting = True
            continue
        if in_voting and s.startswith("### "):
            break
        if in_voting and s.startswith("- "):
            raw = html.unescape(s[2:].strip())
            name, role = split_name_and_role(raw)
            roster.append(ParsedPerson(full_name=name, raw_name=raw, role_hint=role))
    return roster


def _parse_appearances(body: list[str]) -> list[ParsedAppearance]:
    appearances: list[ParsedAppearance] = []
    section = ""
    for line in body:
        s = line.strip()

        # Track current ### section (but NOT #### sub-items).
        sec_m = _SECTION_HEADER.match(s)
        if sec_m:
            section = sec_m["rest"].upper()

        # Invocation: any line containing the canonical phrase.
        inv = _INVOCATION.search(s)
        if inv:
            raw = html.unescape(inv["name"].strip())
            appearances.append(
                ParsedAppearance(
                    person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                    role="invocation",
                )
            )

        # Pledge leader: the #### sub-item under a PLEDGE OF ALLEGIANCE section.
        if "PLEDGE OF ALLEGIANCE" in section and s.startswith("#### "):
            item_m = _ITEM_HEADER.match(s)
            if item_m:
                raw = html.unescape(item_m["rest"].strip())
                appearances.append(
                    ParsedAppearance(
                        person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                        role="pledge",
                    )
                )

        # Visitors: bare-name lines under the INVITATION TO VISITORS section.
        # Exclude blank lines, headers, bullet points, lines starting with "The "
        # (e.g. the introductory prose line), and markdown emphasis markers.
        if "INVITATION TO VISITORS" in section and s and not s.startswith(("#", "-", "The ", "_")):
            raw = html.unescape(s)
            appearances.append(
                ParsedAppearance(
                    person=ParsedPerson(full_name=normalize_name(raw), raw_name=raw),
                    role="speaker",
                )
            )

    return appearances


def parse_minutes_md(text: str) -> ParsedMinutes:
    """Parse a BCSD minutes.md and return roster, per-item outcomes, appearances."""
    body = _split_meeting_minutes(text)
    roster = _parse_roster(body)
    appearances = _parse_appearances(body)

    outcomes: dict[str, ItemOutcome] = {}
    # NOTE (slice 1b): only "#### " agenda items get outcomes. Procedural "### "
    # sections (Approve Agenda, Adjourn, etc.) may carry motions/roll-calls but are
    # not materialized as items this slice; capturing them is a deliberate follow-up.
    #
    # Every "#### <ord>. ..." line becomes an outcome entry, including non-action
    # subitems (e.g. the Pledge student). Those carry empty bodies and join harmlessly
    # to their event.md agenda line in the adapter; the person is also an appearance.
    # Collect all #### item headers with their line positions.
    headers: list[tuple[int, str]] = []
    for idx, line in enumerate(body):
        if _ITEM_HEADER.match(line.strip()):
            headers.append((idx, line.strip()))

    for n, (idx, header) in enumerate(headers):
        end = headers[n + 1][0] if n + 1 < len(headers) else len(body)
        block_lines: list[str] = []
        for j in range(idx + 1, end):
            s = body[j].strip()
            # Stop early if a ### section boundary appears before the next #### item.
            if s.startswith("### "):
                break
            block_lines.append(body[j])

        rest = html.unescape(_ITEM_HEADER.match(header)["rest"])
        code_m = _CODE.search(rest)
        code = code_m.group(1) if code_m else ""
        title = rest
        if code:
            title = title[code_m.end() :].strip()
        # Strip a trailing " (TYPE)" or " (TYPE - Reading)" classifier.
        title = re.sub(r"\s*\([A-Z][^)]*\)\s*$", "", title).strip()

        otext, motions, votes = parse_outcome_block(block_lines)
        status = _derive_status(otext, motions)
        key = code or title
        outcomes[key] = ItemOutcome(
            code=code,
            title=title,
            outcome_text=otext,
            outcome_status=status,
            motions=tuple(motions),
            votes=tuple(votes),
        )

    return ParsedMinutes(
        roster=tuple(roster),
        outcomes=outcomes,
        appearances=tuple(appearances),
    )
