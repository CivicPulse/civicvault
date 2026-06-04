"""Local regression gate: parse every real BCSD minutes.md and assert the parser
attaches every roll call correctly. archive_data/ is gitignored, so this skips
cleanly when the archive is unavailable (e.g. CI)."""

from collections import Counter
from pathlib import Path
from unittest import mock

import pytest

from catalog.ingest.bcsd import adapter as bcsd_adapter
from catalog.ingest.bcsd.adapter import _without_classifier, parse_meeting_folder
from catalog.ingest.bcsd.minutes_md import parse_minutes_md

_ARCHIVE = Path(__file__).resolve().parents[2] / "archive_data" / "bcsd" / "BCSD_BOE_MEETINGS"


def _meeting_folders():
    if not _ARCHIVE.is_dir():
        return []
    return sorted(p.parent for p in _ARCHIVE.rglob("minutes.md"))


@pytest.mark.skipif(not _ARCHIVE.is_dir(), reason="archive_data/ not present (gitignored; CI)")
def test_no_meeting_has_duplicate_or_dropped_votes():
    folders = _meeting_folders()
    assert folders, "archive present but no minutes.md found"

    dup_items, dropped = [], []
    # Skip slow PDF text-extraction — only the event.md<->minutes.md join matters here.
    with mock.patch.object(bcsd_adapter, "extract_pdf_text", lambda p: ("", "unknown")):
        for folder in folders:
            parsed = parse_meeting_folder(folder)

            # (1) No materialized agenda item may contain the same voter twice.
            for item in parsed.agenda_items:
                names = [v.person.full_name for v in item.votes]
                if any(c > 1 for c in Counter(names).values()):
                    dup_items.append((folder.name, item.code or item.title))

            # (2) No vote-bearing minutes outcome may fail to join an event item
            # (which would silently drop those votes). Mirror the adapter's join:
            # an outcome key matches by exact code/title OR by classifier-stripped
            # title (the adapter's fallback), so compare both forms on both sides.
            mins = parse_minutes_md((folder / "minutes.md").read_text(encoding="utf-8"))
            joined = set()
            for item in parsed.agenda_items:
                joined.add(item.code)
                joined.add(item.title)
                joined.add(_without_classifier(item.title))
            for key, oc in mins.outcomes.items():
                if oc.votes and key not in joined and _without_classifier(key) not in joined:
                    dropped.append((folder.name, key, len(oc.votes)))

    assert not dup_items, f"duplicate-voter items: {dup_items[:10]}"
    assert not dropped, f"dropped vote-bearing outcomes: {dropped[:10]}"
