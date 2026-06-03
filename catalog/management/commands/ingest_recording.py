"""Ingest one BCSD recording sidecar set (Source B): MediaAsset + Transcript +
TranscriptSegments + MeetingCoverage. Matcher runs against meetings already in the
DB within ±3 days of the recording's anchor date (brief §6.2)."""

import dataclasses
import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.ingest.bcsd.recording import parse_recording
from catalog.ingest.loader import load_recording
from catalog.ingest.match import match_recording
from catalog.ingest.storage import upload_missing
from catalog.ingest.transcribe import transcribe_flac
from catalog.models import Jurisdiction, Meeting, Source, TranscriptSegment

JURISDICTION = {"slug": "bibb-county-boe", "name": "Bibb County Board of Education"}
SOURCE = {"slug": "bcsd-meeting-recordings", "name": "BCSD Meeting Recordings", "adapter": "bcsd"}
WINDOW_DAYS = 3


class Command(BaseCommand):
    help = "Ingest a BCSD recording sidecar set (Source B) into the catalog."

    def add_arguments(self, parser):
        parser.add_argument("info_json", help="Path to the recording's .info.json file.")
        parser.add_argument(
            "--whisper",
            action="store_true",
            help="If no .vtt is present, transcribe the FLAC with faster-whisper (default: off).",
        )
        parser.add_argument(
            "--upload",
            action="store_true",
            help="Upload the recording's media (mp4/flac) to R2 where missing (default: off).",
        )

    def handle(self, *args, **options):
        info_path = Path(options["info_json"])
        if not info_path.is_file():
            raise CommandError(f"Not a file: {info_path}")

        parsed = parse_recording(info_path)

        # Fallback transcription when there is no .vtt and --whisper was requested.
        if not parsed.segments and options["whisper"]:
            flac = self._find_flac(info_path, parsed.youtube_id)
            if flac is None:
                raise CommandError(f"--whisper given but no .flac found for {parsed.youtube_id}")
            segments = transcribe_flac(flac)
            parsed = dataclasses.replace(parsed, segments=segments, transcript_origin="whisper")

        jurisdiction, _ = Jurisdiction.objects.get_or_create(
            slug=JURISDICTION["slug"], defaults={"name": JURISDICTION["name"]}
        )
        source, _ = Source.objects.get_or_create(
            slug=SOURCE["slug"],
            defaults={
                "name": SOURCE["name"],
                "adapter": SOURCE["adapter"],
                "jurisdiction": jurisdiction,
            },
        )

        candidates = self._candidate_meetings(parsed)
        decisions = match_recording(parsed, candidates)
        media = load_recording(parsed, decisions, source=source)

        uploaded = 0
        if options["upload"] and parsed.r2_key:
            mp4 = self._find_sibling(info_path, parsed.youtube_id, ".mp4")
            if mp4 and upload_missing(parsed.r2_key, mp4):
                uploaded += 1
        upload_note = f"({uploaded} uploaded to R2)" if options["upload"] else "(upload skipped)"

        split = decisions[0].end_offset if len(decisions) == 2 else None
        segment_count = TranscriptSegment.objects.filter(transcript__media=media).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"Ingested recording {media.youtube_id}: "
                f"{segment_count} segments, "
                f"{len(decisions)} coverage window(s), "
                f"split={split}, "
                f"{'unlinked' if not decisions else 'linked'} {upload_note}."
            )
        )

    def _candidate_meetings(self, parsed):
        anchor = parsed.recorded_on or parsed.upload_date
        if anchor is None:
            return []
        lo = anchor - datetime.timedelta(days=WINDOW_DAYS)
        hi = anchor + datetime.timedelta(days=WINDOW_DAYS)
        return list(Meeting.objects.filter(date__gte=lo, date__lte=hi))

    def _find_sibling(self, info_path, youtube_id, suffix):
        for f in info_path.parent.iterdir():
            if youtube_id in f.name and f.name.endswith(suffix):
                return f
        return None

    def _find_flac(self, info_path, youtube_id):
        return self._find_sibling(info_path, youtube_id, ".flac")
