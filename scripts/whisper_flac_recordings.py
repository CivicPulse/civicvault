#!/usr/bin/env python
"""Transcribe the flac-only recordings (no .vtt) with faster-whisper, 2022+.

The dev import (scripts/import_dev_years.py) loads recordings WITHOUT --whisper,
so the ~10 recordings that ship only a .flac land as media + coverage with zero
transcript segments. This backfills them: it re-runs `ingest_recording --whisper`
for each, which deletes the empty transcript and recreates it from whisper output
(load_recording wipes transcripts/coverages before rebuild, so no duplicates).

Speed depends on the device. With the `gpu` dependency-group installed (the
nvidia-*-cu12 CUDA 12 wheels), transcribe_flac runs on the GPU — seconds per
recording. Without it, faster-whisper `base` runs on CPU (~10-30 min each).
Idempotent and restartable — a re-run just re-transcribes.

Run (GPU):  uv run --group ingest --group gpu python scripts/whisper_flac_recordings.py
Run (CPU):  uv run --group ingest python scripts/whisper_flac_recordings.py
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civicvault.settings")

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402

REC_DIR = ROOT / "archive_data" / "bcsd" / "BCSD_MEETING_RECORDINGS"
# Years to transcribe: from the CLI (e.g. `… whisper_flac_recordings.py 2021`) or
# everything 2020+. Pass explicit years to avoid re-transcribing recordings that
# already have whisper transcripts (harmless, just wasted GPU time).
_ARGV_YEARS = tuple(int(a) for a in sys.argv[1:] if a.isdigit())

# Recordings to skip, keyed by YouTube id (a substring of the .info.json name).
# b_mXGkrYIznfU is a ~12h livestream outlier — far longer than any real meeting;
# transcribing it would dominate the run and yield an unwieldy transcript. It
# stays ingested as media + coverage (no transcript segments).
SKIP_IDS = {"b_mXGkrYIznfU"}


def _is_skipped(info: Path) -> bool:
    return any(sid in info.name for sid in SKIP_IDS)


def _flac_only_infos():
    """Recordings (in the wanted years) that have a .flac but no .vtt (whisper needed)."""
    out = []
    for info in sorted(REC_DIR.glob("*.info.json")):
        if not info.name[:4].isdigit():
            continue
        year = int(info.name[:4])
        if (_ARGV_YEARS and year not in _ARGV_YEARS) or year < 2020:
            continue
        base = info.name[: -len(".info.json")]
        has_vtt = any(REC_DIR.glob(f"{base}*.vtt"))
        has_flac = any(REC_DIR.glob(f"{base}*.flac"))
        if has_flac and not has_vtt:
            out.append(info)
    return out


def main():
    infos = _flac_only_infos()
    skipped = [j for j in infos if _is_skipped(j)]
    infos = [j for j in infos if not _is_skipped(j)]
    for j in skipped:
        print(f"  [skip] {j.name[:60]}… (in SKIP_IDS)", flush=True)
    total = len(infos)
    print(f"== whisper: {total} flac-only recordings to transcribe ==", flush=True)
    ok = fail = 0
    for i, info in enumerate(infos, 1):
        t0 = time.monotonic()
        print(f"[{i}/{total}] {info.name[:60]}… transcribing", flush=True)
        try:
            call_command("ingest_recording", str(info), whisper=True, verbosity=0)
            ok += 1
            print(f"[{i}/{total}] done in {time.monotonic() - t0:.0f}s", flush=True)
        except Exception as exc:
            fail += 1
            print(f"[{i}/{total}] FAIL: {exc}", file=sys.stderr, flush=True)
    print(f"\nDONE — whisper ok={ok} fail={fail} of {total}", flush=True)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
