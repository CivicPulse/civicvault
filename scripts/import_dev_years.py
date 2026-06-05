#!/usr/bin/env python
"""Dev convenience: load the BCSD catalog + recordings for 2022 onward.

Faithful to the documented per-folder ingest — it calls the very same management
commands (`ingest_bcsd`, `ingest_recording`) — but runs them in a single process
so 300+ folders don't each pay Django's startup cost. Meetings are loaded before
recordings because the recording matcher links a recording to meetings already in
the DB within +/-3 days.

Idempotent: both commands key on stable source ids (update_or_create), so a re-run
refreshes rather than duplicates. Recordings are ingested WITHOUT --whisper, so the
~10 flac-only recordings load as media + coverage with zero transcript segments;
whisper them later as a separate job.

Run:  uv run python scripts/import_dev_years.py
"""

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # run-as-script puts scripts/ on the path, not the repo root
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civicvault.settings")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

MEET_ROOT = ROOT / "archive_data" / "bcsd" / "BCSD_BOE_MEETINGS"
REC_DIR = ROOT / "archive_data" / "bcsd" / "BCSD_MEETING_RECORDINGS"
DEFAULT_YEARS = (2020, 2021, 2022, 2023, 2024, 2025, 2026)
# Years to ingest: from the CLI (e.g. `… import_dev_years.py 2020 2021`) or the
# full set. Pass explicit years when EXTENDING an existing dev DB — re-ingesting a
# year re-runs ingest_recording WITHOUT --whisper, which wipes any whisper
# transcripts already built for that year's recordings.
YEARS = tuple(int(a) for a in sys.argv[1:] if a.isdigit()) or DEFAULT_YEARS
_SINK = io.StringIO()  # swallow each command's per-item success line; we print progress


def _meeting_folders():
    """Every leaf meeting folder under YEAR/MM/ for the wanted years, sorted."""
    folders = []
    for year in YEARS:
        ybase = MEET_ROOT / str(year)
        if not ybase.is_dir():
            continue
        for month in sorted(p for p in ybase.iterdir() if p.is_dir()):
            folders.extend(sorted(p for p in month.iterdir() if p.is_dir()))
    return folders


def _recording_infos():
    """Every recording .info.json whose date-prefixed name is in the wanted years."""
    return sorted(
        j
        for j in REC_DIR.glob("*.info.json")
        if j.name[:4].isdigit() and int(j.name[:4]) in YEARS
    )


def _run(label, items, command):
    ok = fail = 0
    total = len(items)
    print(f"== {label}: {total} to ingest ==", flush=True)
    for i, item in enumerate(items, 1):
        try:
            call_command(command, str(item), verbosity=0, stdout=_SINK, stderr=_SINK)
            ok += 1
        except Exception as exc:  # one bad folder must not abort the batch
            fail += 1
            print(f"  [FAIL] {Path(item).name}: {exc}", file=sys.stderr, flush=True)
        if i % 25 == 0 or i == total:
            print(f"  {label} {i}/{total} (ok={ok} fail={fail})", flush=True)
    return ok, fail


def main():
    m_ok, m_fail = _run("meetings", _meeting_folders(), "ingest_bcsd")
    r_ok, r_fail = _run("recordings", _recording_infos(), "ingest_recording")
    print(
        f"\nDONE — meetings ok={m_ok} fail={m_fail} | recordings ok={r_ok} fail={r_fail}",
        flush=True,
    )
    if m_fail or r_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
