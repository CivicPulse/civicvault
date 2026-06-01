"""Parse a BCSD meeting folder name (brief §4.1).

Format: YYYY-MM-DD_HHMM_<type-slug>_mid-<MeetingID>
The type-slug may contain hyphens, so anchor on the trailing `_mid-<id>`.
"""

import datetime
import re
from dataclasses import dataclass

_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{4})_(?P<slug>.+)_mid-(?P<mid>\d+)$"
)


@dataclass(frozen=True)
class ParsedFolderName:
    date: datetime.date
    start_time: datetime.time
    type_slug: str
    meeting_id: str


def parse_folder_name(name: str) -> ParsedFolderName:
    m = _PATTERN.match(name.strip())
    if not m:
        raise ValueError(f"Not a BCSD meeting folder name: {name!r}")
    date = datetime.date.fromisoformat(m["date"])
    hhmm = m["time"]
    start_time = datetime.time(int(hhmm[:2]), int(hhmm[2:]))
    return ParsedFolderName(
        date=date, start_time=start_time, type_slug=m["slug"], meeting_id=m["mid"]
    )
