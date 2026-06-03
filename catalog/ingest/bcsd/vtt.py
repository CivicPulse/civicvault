"""Dedup YouTube auto-caption WebVTT into clean, non-overlapping transcript
segments (brief §5.6). Pure: takes the .vtt text, returns IR dataclasses.

The YouTube rolling-window format repeats each line as it "types out": a real
multi-second cue carries the previous committed line (carryover) followed by the
new line with inline <ts><c>word</c> tags; a ~10ms preview cue then restates the
new line as plain text. The new content of any cue is its last non-empty cleaned
line; we emit it only when it differs from the last emitted line, which collapses
carryover lines, preview cues, and consecutive repeats.
"""

import dataclasses
import re

from catalog.ingest.ir import ParsedTranscriptSegment

_CUE_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})")
_INLINE_TS = re.compile(r"<\d{2}:\d{2}:\d{2}\.\d{3}>")
_C_TAG = re.compile(r"</?c[^>]*>")
_NOISE = re.compile(r"^\[[^\]]*\]$")  # [Music], [Applause], ...
_WS = re.compile(r"\s+")


def _to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _clean(line: str) -> str:
    line = _INLINE_TS.sub("", line)
    line = _C_TAG.sub("", line)
    return _WS.sub(" ", line).strip()


def _cues(text: str):
    """Yield (start, end, [text_lines]) per cue block.

    WebVTT cue blocks are separated by *empty* lines (no characters at all).
    A line that contains only whitespace (e.g. a space used as a carryover
    placeholder) is part of the cue payload, not a separator.
    """
    block: list[str] = []
    for raw in text.splitlines():
        if raw == "":
            if block:
                yield block
                block = []
        else:
            block.append(raw)
    if block:
        yield block


def parse_vtt(text: str) -> tuple[ParsedTranscriptSegment, ...]:
    segments: list[ParsedTranscriptSegment] = []
    last_text: str | None = None
    for block in _cues(text):
        m = _CUE_TIME.match(block[0])
        if not m:
            continue  # WEBVTT header / NOTE / Kind / Language blocks
        start = _to_seconds(*m.group(1, 2, 3, 4))
        end = _to_seconds(*m.group(5, 6, 7, 8))
        cleaned = [c for c in (_clean(line) for line in block[1:]) if c and not _NOISE.match(c)]
        if not cleaned:
            continue
        content = cleaned[-1]  # the new content is the last cleaned line
        if content == last_text:
            continue
        if segments:  # clamp the previous segment's end to this start (non-overlapping)
            segments[-1] = dataclasses.replace(segments[-1], end=start)
        segments.append(ParsedTranscriptSegment(start=start, end=end, text=content))
        last_text = content
    return tuple(segments)
