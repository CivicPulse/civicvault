"""Parse a BCSD minutes outcome block: motion variants + roll call (brief §5.2)."""

import re

from catalog.ingest.ir import ParsedMotion, ParsedPerson, ParsedVote
from catalog.ingest.names import normalize_name

# Strip an optional leading "- " bullet, tolerate the four label forms.
_MOVED = re.compile(r"^-?\s*(Initial |Amended )?Motion made by:\s*(?P<name>.+?)\s*$")
_SECONDED = re.compile(r"^-?\s*(Initial |Amended )?Motion seconded by:\s*(?P<name>.+?)\s*$")
_VOTING = re.compile(r"^-?\s*(?:_?Voting(?: results)?:?_?)\s*(?P<result>.+?)\s*$", re.IGNORECASE)
_ROLL = re.compile(r"^-\s*(?P<label>Yes|No|Abstain|Absent):\s*(?P<name>.+?)\s*$", re.IGNORECASE)

_ROLL_VALUE = {"yes": "yea", "no": "nay", "abstain": "abstain", "absent": "absent"}


def _person(raw: str) -> ParsedPerson:
    return ParsedPerson(full_name=normalize_name(raw), raw_name=raw.strip())


def _status(result_text: str) -> str:
    low = result_text.lower()
    if "unanim" in low:
        return "unanimous"
    if "fail" in low or "denied" in low or "not approved" in low:
        return "failed"
    if result_text:
        return "passed"
    return "none"


def parse_outcome_block(lines: list[str]) -> tuple[str, list[ParsedMotion], list[ParsedVote]]:
    """Return (outcome_text, motions, roll_call_votes) for one agenda item."""
    motions: list[ParsedMotion] = []
    votes: list[ParsedVote] = []
    prose: list[str] = []

    # Working state for the motion currently being assembled.
    cur_kind = "simple"
    cur_moved: ParsedPerson | None = None
    cur_seconded: ParsedPerson | None = None
    seq = 0
    have_motion_signal = False

    def flush(result_text: str):
        nonlocal cur_kind, cur_moved, cur_seconded, seq, have_motion_signal
        if not have_motion_signal and not result_text:
            return
        motions.append(
            ParsedMotion(
                kind=cur_kind,
                sequence=seq,
                moved_by=cur_moved,
                seconded_by=cur_seconded,
                result_text=result_text.strip(),
                status=_status(result_text),
            )
        )
        seq += 1
        # After flushing an initial motion, the next motion in this block is its amendment.
        cur_kind = "amended" if cur_kind == "initial" else "simple"
        cur_moved = None
        cur_seconded = None
        have_motion_signal = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        roll_m = _ROLL.match(line)
        if roll_m:
            votes.append(
                ParsedVote(
                    person=_person(roll_m["name"]),
                    value=_ROLL_VALUE[roll_m["label"].lower()],
                )
            )
            continue
        moved_m = _MOVED.match(line)
        if moved_m:
            label = (moved_m.group(1) or "").strip().lower()
            if label == "initial":
                cur_kind = "initial"
            elif label == "amended":
                if cur_kind == "initial":  # flush the accumulated initial motion first
                    flush("")
                cur_kind = "amended"
            cur_moved = _person(moved_m["name"])
            have_motion_signal = True
            continue
        seconded_m = _SECONDED.match(line)
        if seconded_m:
            cur_seconded = _person(seconded_m["name"])
            have_motion_signal = True
            continue
        voting_m = _VOTING.match(line)
        if voting_m and have_motion_signal:
            flush(voting_m["result"])
            continue
        prose.append(line)

    # An item may end with a dangling motion that never had an explicit result line.
    if have_motion_signal:
        flush("")

    return "\n".join(prose).strip(), motions, votes
