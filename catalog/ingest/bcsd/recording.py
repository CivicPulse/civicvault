"""Parse a BCSD recording sidecar set (brief §5.4–5.6) into a ParsedRecording.
Reads files (the .info.json + its sibling .vtt); the VTT dedup itself is pure
(catalog.ingest.bcsd.vtt). Title-date parsing handles the §6.2 format spread."""

import datetime
import json
import re
from pathlib import Path

from catalog.ingest.bcsd.files import r2_key_for
from catalog.ingest.bcsd.vtt import parse_vtt
from catalog.ingest.ir import ParsedRecording

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/_.](\d{1,2})[/_.](\d{4})\b")
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
_MONTH_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")[ _](\d{1,2})[ _,]+(\d{4})\b", re.IGNORECASE
)


def parse_title_date(title: str) -> datetime.date | None:
    """Meeting date from the recording title across the §6.2 formats. None if absent."""
    m = _NUMERIC_DATE.search(title)
    if m:
        month, day, year = (int(g) for g in m.groups())
        try:
            return datetime.date(year, month, day)
        except ValueError:
            return None
    m = _MONTH_DATE.search(title)
    if m:
        month = _MONTHS[m.group(1).lower()]
        try:
            return datetime.date(int(m.group(3)), month, int(m.group(2)))
        except ValueError:
            return None
    return None


def _upload_date(raw: str | None) -> datetime.date | None:
    if not raw or len(raw) != 8:
        return None
    return datetime.date(int(raw[0:4]), int(raw[4:6]), int(raw[6:8]))


def _r2_key_or_blank(path: Path) -> str:
    """recordings may live outside a BCSD_* tree (e.g. tmp test dirs) → blank,
    unlike attachments which must be keyable. Keys only matter for opt-in upload."""
    try:
        return r2_key_for(path)
    except ValueError:
        return ""


def _find_vtt(info_path: Path, youtube_id: str) -> Path | None:
    """Prefer .en.vtt, fall back to .en-orig.vtt; tolerate _./__ separators by
    matching any sibling that contains the youtube id and ends with the suffix."""
    siblings = list(info_path.parent.iterdir())
    for suffix in (".en.vtt", ".en-orig.vtt"):
        for f in siblings:
            if youtube_id in f.name and f.name.endswith(suffix):
                return f
    return None


def _find_mp4(info_path: Path, youtube_id: str) -> Path | None:
    for f in info_path.parent.iterdir():
        if youtube_id in f.name and f.name.endswith(".mp4"):
            return f
    return None


def parse_recording(info_path: Path) -> ParsedRecording:
    info = json.loads(Path(info_path).read_text())
    youtube_id = info["id"]
    title = info.get("title") or info.get("fulltitle") or ""

    vtt = _find_vtt(Path(info_path), youtube_id)
    if vtt is not None:
        segments = parse_vtt(vtt.read_text())
        origin = "youtube_captions"
    else:
        segments = ()
        origin = ""

    mp4 = _find_mp4(Path(info_path), youtube_id)
    r2_key = _r2_key_or_blank(mp4) if mp4 is not None else ""

    return ParsedRecording(
        youtube_id=youtube_id,
        title=title,
        recorded_on=parse_title_date(title),
        upload_date=_upload_date(info.get("upload_date")),
        duration_seconds=info.get("duration"),
        source_url=info.get("webpage_url", ""),
        r2_key=r2_key,
        is_combined=("committee" in title.lower() and "board" in title.lower()),
        segments=segments,
        transcript_origin=origin,
        source_path=str(info_path),
    )
