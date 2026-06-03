"""Recording↔meeting matcher (brief §6). Agency-agnostic core: given a
ParsedRecording and the candidate Meeting rows on its date, decide the
MeetingCoverage windows (0, 1, or 2) and the suggested committee→board split.

The split is always a suggestion (split_confirmed=False); an admin confirms it
later via the scrubber tool. The earlier-by-start_time meeting is the committee
window — derived from time, not from any agency's kind vocabulary."""

import datetime
import logging
import re
from dataclasses import dataclass

from catalog.ingest.ir import ParsedRecording

logger = logging.getLogger(__name__)
_TO_ORDER = re.compile(r"\bto order\b", re.IGNORECASE)


@dataclass(frozen=True)
class CoverageDecision:
    meeting_id: int
    start_offset: float
    end_offset: float | None  # None = to end of recording
    split_confirmed: bool = False


def suggest_split(segments) -> float | None:
    """§6.4: the SECOND 'to order' marks the board meeting's start (committee is
    first). Fewer than two markers → None (caller falls back conservatively)."""
    hits = [s.start for s in segments if _TO_ORDER.search(s.text)]
    return hits[1] if len(hits) >= 2 else None


def _sort_key(meeting):
    # start_time first (committee earlier), then date, then pk — all agency-neutral.
    return (meeting.start_time or datetime.time.min, meeting.date, meeting.pk)


def match_recording(parsed: ParsedRecording, candidate_meetings) -> list[CoverageDecision]:
    meetings = sorted(candidate_meetings, key=_sort_key)

    if not meetings:
        return []  # unlinked MediaAsset (e.g. a non-meeting video)

    if len(meetings) == 1:
        return [CoverageDecision(meeting_id=meetings[0].pk, start_offset=0.0, end_offset=None)]

    # Two (or more) meetings on the date. For slice 1d we handle the committee+board
    # combined case; take the two earliest by start time. (Duplicate/at-scale handling
    # is Phase 2.)
    committee, board = meetings[0], meetings[1]
    if len(meetings) > 2:
        logger.warning(
            "More than two candidate meetings for recording %s; using the two earliest.",
            parsed.youtube_id,
        )

    split = suggest_split(parsed.segments) if parsed.is_combined else None
    if split is None:
        # §6.4 conservative choice: do not guess a midpoint. One full-span window on
        # the earlier meeting, flagged for manual split.
        logger.warning(
            "No split marker for combined recording %s; one full-span window on %s, "
            "manual split needed.",
            parsed.youtube_id,
            committee.pk,
        )
        return [CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=None)]

    return [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=split),
        CoverageDecision(meeting_id=board.pk, start_offset=split, end_offset=None),
    ]
