# CivicVault Slice 1d — Recordings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest BCSD meeting recordings (Source B) — parse the sidecar set into a `MediaAsset`, dedup the YouTube auto-caption `.vtt` into `TranscriptSegment`s, and run the §6 matcher to create `MeetingCoverage` rows (including the combined committee+board → two-windows + split-suggestion case).

**Architecture:** Mirrors the slice 1b/1c pipeline — pure parsers under `catalog/ingest/bcsd/` → frozen IR dataclasses in `catalog/ingest/ir.py` → agency-agnostic core (`match.py`, `transcribe.py`, `load_recording` in `loader.py`) → a thin `ingest_recording` management command. The matcher and whisper helper live in core (not under `bcsd/`) so agency #2 reuses them unchanged.

**Tech Stack:** Python 3.13, Django, PostgreSQL FTS (`tsvector` + GIN + trigger), `faster-whisper` (opt-in, mocked in CI), pytest. Always `uv run`. `ruff` clean before every commit.

**Spec:** `docs/superpowers/specs/2026-06-03-civicvault-1d-recordings-design.md`.

**Branch:** `feat/1d-recordings` (already created; the spec is committed there).

**Reference fixture (manual smoke only):** `archive_data/bcsd/BCSD_MEETING_RECORDINGS/2023-01-20-...CWjfBn10EJc_.*` + meeting folders `BCSD_BOE_MEETINGS/2023/01/2023-01-19_1600_committee-meeting_mid-107503` and `..._1830_board-meeting_mid-107593`.

---

## Conventions (read once)

- **Run tests:** `uv run pytest <path> -v`. Full suite: `uv run pytest -q` (expect **119 passing** at the start of this slice).
- **DB:** `docker compose up -d db` must be running (host port 5433). Do NOT pass `--reuse-db`.
- **Pre-commit gate (every task):** `uv run ruff check . && uv run ruff format --check .` then `uv run pytest -q`.
- **Commits:** Conventional Commits, one per task. `migrations/` and `archive_data/` are ruff-excluded.
- **Pure modules import NO Django** (`ir.py`, `bcsd/vtt.py`, `bcsd/recording.py` except it reads files, `match.py`, `transcribe.py`). Only `loader.py`, models, migrations, the command, and DB tests import Django.

---

## Task 1: Add faster-whisper dependency

**Files:**
- Modify: `pyproject.toml` (via `uv add`)

- [ ] **Step 1: Add the dependency**

Run: `uv add faster-whisper`

- [ ] **Step 2: Verify it imports**

Run: `uv run python -c "import faster_whisper; print(faster_whisper.__version__)"`
Expected: prints a version string, no error. (This does NOT download model weights — that only happens on `WhisperModel(...)` instantiation, which CI never does.)

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add faster-whisper for recording transcription (opt-in)"
```

---

## Task 2: IR dataclasses — ParsedTranscriptSegment, ParsedRecording

**Files:**
- Modify: `catalog/ingest/ir.py`
- Test: `catalog/tests/test_ingest_ir.py`

- [ ] **Step 1: Write the failing test**

Append to `catalog/tests/test_ingest_ir.py`:

```python
def test_parsed_transcript_segment_is_frozen():
    from catalog.ingest.ir import ParsedTranscriptSegment

    seg = ParsedTranscriptSegment(start=1.5, end=3.0, text="hello")
    assert seg.start == 1.5 and seg.end == 3.0 and seg.text == "hello"
    with pytest.raises(dataclasses.FrozenInstanceError):
        seg.text = "x"


def test_parsed_recording_defaults():
    import datetime

    from catalog.ingest.ir import ParsedRecording, ParsedTranscriptSegment

    rec = ParsedRecording(
        youtube_id="CWjfBn10EJc",
        title="Committee and Board Meeting 1/19/2023",
        recorded_on=datetime.date(2023, 1, 19),
        upload_date=datetime.date(2023, 1, 20),
        duration_seconds=13486,
        source_url="https://www.youtube.com/watch?v=CWjfBn10EJc",
        r2_key="",
        is_combined=True,
    )
    assert rec.segments == ()
    assert rec.transcript_origin == "youtube_captions"
    assert rec.source_path == ""
    # segments accept ParsedTranscriptSegment tuples
    rec2 = dataclasses.replace(rec, segments=(ParsedTranscriptSegment(0.0, 1.0, "x"),))
    assert rec2.segments[0].text == "x"
```

Confirm the test file already imports `dataclasses` and `pytest` at the top; if not, add `import dataclasses` and `import pytest`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_ir.py -v -k "transcript_segment or recording_defaults"`
Expected: FAIL — `ImportError: cannot import name 'ParsedTranscriptSegment'`.

- [ ] **Step 3: Add the dataclasses**

Append to `catalog/ingest/ir.py` (the module already imports `datetime` and `from dataclasses import dataclass`):

```python
@dataclass(frozen=True)
class ParsedTranscriptSegment:
    """A timed transcript line. `start` is the absolute offset in the recording
    (= the YouTube ?t= value), powering transcript→video deep links (brief §7)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ParsedRecording:
    """A recording's sidecar set (brief §5.4–5.6), framework-neutral."""

    youtube_id: str
    title: str
    recorded_on: datetime.date | None  # parsed from title (§6.2); preferred anchor
    upload_date: datetime.date | None  # info.json upload_date (§5.5); fallback anchor
    duration_seconds: int | None
    source_url: str
    r2_key: str  # "BCSD/..." (§1c convention); "" when not under a BCSD_* dir
    is_combined: bool  # title mentions both "Committee" and "Board"
    segments: tuple[ParsedTranscriptSegment, ...] = ()
    transcript_origin: str = "youtube_captions"  # "youtube_captions" | "whisper" | ""
    source_path: str = ""  # the .info.json path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_ir.py -v`
Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/ir.py catalog/tests/test_ingest_ir.py
git commit -m "feat(ingest): add ParsedTranscriptSegment + ParsedRecording IR dataclasses"
```

---

## Task 3: VTT rolling-window dedup importer (highest risk — TDD)

**Files:**
- Create: `catalog/ingest/bcsd/vtt.py`
- Test: `catalog/tests/test_bcsd_vtt.py`

Background: YouTube auto-caption cues interleave a real multi-second cue (line 1 = carryover of the previous committed text; line 2 = the NEW content carrying inline `<00:..><c>word</c>` tags) with a ~10ms "preview" cue that restates the new content as plain text. The new content of any cue is its **last non-empty cleaned line**; we emit it only when it differs from the previously emitted line, which drops carryover lines, preview cues, and consecutive repeats.

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_bcsd_vtt.py`:

```python
from catalog.ingest.bcsd.vtt import parse_vtt

# Mirrors the real BCSD format: real cue (carryover + tagged new line),
# then a 10ms preview cue restating the new line as plain text.
ROLLING = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
good<00:00:00.500><c> afternoon</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
good afternoon
 

00:00:02.000 --> 00:00:04.000 align:start position:0%
good afternoon
the<00:00:02.500><c> board</c><00:00:03.000><c> will</c><00:00:03.500><c> come</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
the board will come
 

00:00:04.000 --> 00:00:06.000 align:start position:0%
the board will come
[Music]
"""


def test_dedup_emits_each_phrase_once():
    segs = parse_vtt(ROLLING)
    texts = [s.text for s in segs]
    assert texts == ["good afternoon", "the board will come"]


def test_inline_tags_are_stripped():
    segs = parse_vtt(ROLLING)
    assert all("<" not in s.text and "</c>" not in s.text for s in segs)


def test_music_noise_is_dropped():
    segs = parse_vtt(ROLLING)
    assert all("[Music]" not in s.text for s in segs)


def test_starts_are_monotonic_and_nonoverlapping():
    segs = parse_vtt(ROLLING)
    assert segs[0].start == 0.0
    assert segs[1].start == 2.0
    # each segment's end is clamped to the next segment's start
    assert segs[0].end == segs[1].start
    for a, b in zip(segs, segs[1:]):
        assert a.start < b.start
        assert a.end <= b.start


def test_empty_input_returns_empty_tuple():
    assert parse_vtt("WEBVTT\n\n") == ()


def test_seconds_conversion_handles_hours():
    vtt = (
        "WEBVTT\n\n"
        "01:02:03.500 --> 01:02:05.000 align:start position:0%\n"
        "hello world\n"
    )
    segs = parse_vtt(vtt)
    assert segs[0].start == 3723.5  # 1h2m3.5s
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_bcsd_vtt.py -v`
Expected: FAIL — `ModuleNotFoundError: catalog.ingest.bcsd.vtt`.

- [ ] **Step 3: Implement `vtt.py`**

Create `catalog/ingest/bcsd/vtt.py`:

```python
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

_CUE_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
)
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
    """Yield (start, end, [text_lines]) per cue block."""
    block: list[str] = []
    for raw in text.splitlines():
        if raw.strip() == "":
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_bcsd_vtt.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/vtt.py catalog/tests/test_bcsd_vtt.py
git commit -m "feat(ingest): YouTube VTT rolling-window dedup importer"
```

---

## Task 4: Recording sidecar + info.json + title-date parsing

**Files:**
- Create: `catalog/ingest/bcsd/recording.py`
- Test: `catalog/tests/test_bcsd_recording.py`
- Test fixtures: `catalog/tests/fixtures/recordings/` (created here)

`parse_recording` reads a `.info.json` path, finds the matching `.vtt` sidecar (prefer `.en.vtt`, fall back `.en-orig.vtt`, tolerant of `_.`/`__`), and builds a `ParsedRecording`. The r2_key points at the `.mp4` (the primary media) via the slice-1c `BCSD/...` convention; blank when no `.mp4` or no `BCSD_*` ancestor.

- [ ] **Step 1: Create test fixtures**

Create `catalog/tests/fixtures/recordings/BCSD_MEETING_RECORDINGS/test_committee_and_board_1_19_2023_TESTvideo01_.info.json`:

```json
{
  "id": "TESTvideo01",
  "title": "Bibb County School District Committee and Board Meeting 1/19/2023",
  "fulltitle": "Bibb County School District Committee and Board Meeting 1/19/2023",
  "duration": 120,
  "upload_date": "20230120",
  "webpage_url": "https://www.youtube.com/watch?v=TESTvideo01",
  "channel": "bibbschools",
  "chapters": null
}
```

Create `catalog/tests/fixtures/recordings/BCSD_MEETING_RECORDINGS/test_committee_and_board_1_19_2023_TESTvideo01_.en.vtt`:

```
WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start position:0%
 
committee<00:00:01.500><c> meeting</c><00:00:02.000><c> call</c><00:00:02.500><c> to</c><00:00:02.800><c> order</c>

00:00:03.000 --> 00:00:03.010 align:start position:0%
committee meeting call to order
 

00:00:03.000 --> 00:00:05.000 align:start position:0%
committee meeting call to order
some<00:00:03.500><c> committee</c><00:00:04.000><c> business</c>

00:01:00.000 --> 00:01:02.000 align:start position:0%
some committee business
we<00:01:00.500><c> now</c><00:01:01.000><c> come</c><00:01:01.500><c> to</c><00:01:01.800><c> order</c>

00:01:02.000 --> 00:01:04.000 align:start position:0%
we now come to order
board<00:01:02.500><c> business</c>
```

Create empty `catalog/tests/fixtures/recordings/__init__.py` so the dir is import-safe (path-based tests don't need it, but keep the package tidy):

(empty file)

- [ ] **Step 2: Write the failing tests**

Create `catalog/tests/test_bcsd_recording.py`:

```python
import datetime
from pathlib import Path

import pytest

from catalog.ingest.bcsd.recording import parse_recording, parse_title_date

FIX = Path(__file__).parent / "fixtures" / "recordings" / "BCSD_MEETING_RECORDINGS"
INFO = FIX / "test_committee_and_board_1_19_2023_TESTvideo01_.info.json"


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Meeting 1/19/2023", datetime.date(2023, 1, 19)),
        ("Meeting 1_19_2023", datetime.date(2023, 1, 19)),
        ("Meeting 04.15.2021", datetime.date(2021, 4, 15)),
        ("Town Hall June 17 2021", datetime.date(2021, 6, 17)),
        ("Town Hall August_19_2021", datetime.date(2021, 8, 19)),
        ("No date here", None),
    ],
)
def test_parse_title_date(title, expected):
    assert parse_title_date(title) == expected


def test_parse_recording_builds_full_record():
    rec = parse_recording(INFO)
    assert rec.youtube_id == "TESTvideo01"
    assert rec.recorded_on == datetime.date(2023, 1, 19)
    assert rec.upload_date == datetime.date(2023, 1, 20)
    assert rec.duration_seconds == 120
    assert rec.is_combined is True
    assert rec.transcript_origin == "youtube_captions"
    assert rec.source_url == "https://www.youtube.com/watch?v=TESTvideo01"
    # the .vtt was found, deduped, and has the two "to order" markers for the splitter
    assert len(rec.segments) >= 3
    assert sum("to order" in s.text for s in rec.segments) == 2


def test_parse_recording_r2_key_uses_bcsd_convention():
    rec = parse_recording(INFO)
    # no .mp4 in the fixture set → blank r2_key (uploads are opt-in)
    assert rec.r2_key == ""


def test_parse_recording_without_vtt_flags_empty_transcript(tmp_path):
    info = tmp_path / "novtt_TESTvideo99_.info.json"
    info.write_text(
        '{"id": "TESTvideo99", "title": "Board Meeting 2/2/2023", '
        '"duration": 60, "upload_date": "20230203", '
        '"webpage_url": "https://youtu.be/TESTvideo99"}'
    )
    rec = parse_recording(info)
    assert rec.segments == ()
    assert rec.transcript_origin == ""
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_bcsd_recording.py -v`
Expected: FAIL — `ModuleNotFoundError: catalog.ingest.bcsd.recording`.

- [ ] **Step 4: Implement `recording.py`**

Create `catalog/ingest/bcsd/recording.py`:

```python
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
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_bcsd_recording.py -v`
Expected: PASS (all). Note: `test_parse_recording_builds_full_record` proves the `.vtt` is found + deduped and that exactly two segments contain "to order" (the split markers).

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/bcsd/recording.py catalog/tests/test_bcsd_recording.py catalog/tests/fixtures/recordings/
git commit -m "feat(ingest): parse recording sidecar set (info.json + vtt + title date)"
```

---

## Task 5: faster-whisper helper (opt-in, mocked in CI)

**Files:**
- Create: `catalog/ingest/transcribe.py`
- Test: `catalog/tests/test_ingest_transcribe.py`

- [ ] **Step 1: Write the failing test**

Create `catalog/tests/test_ingest_transcribe.py`:

```python
from types import SimpleNamespace
from unittest import mock

from catalog.ingest.transcribe import transcribe_flac


def test_transcribe_flac_maps_segments_to_ir():
    fake_segments = [
        SimpleNamespace(start=0.0, end=1.2, text=" hello "),
        SimpleNamespace(start=1.2, end=2.5, text="world"),
    ]
    fake_model = mock.Mock()
    fake_model.transcribe.return_value = (iter(fake_segments), object())
    with mock.patch("catalog.ingest.transcribe.WhisperModel", return_value=fake_model) as mk:
        out = transcribe_flac("/tmp/x.flac", model_size="tiny")

    mk.assert_called_once_with("tiny")
    fake_model.transcribe.assert_called_once_with("/tmp/x.flac")
    assert [(s.start, s.end, s.text) for s in out] == [(0.0, 1.2, "hello"), (1.2, 2.5, "world")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest catalog/tests/test_ingest_transcribe.py -v`
Expected: FAIL — `ModuleNotFoundError: catalog.ingest.transcribe`.

- [ ] **Step 3: Implement `transcribe.py`**

Create `catalog/ingest/transcribe.py`:

```python
"""Opt-in faster-whisper transcription of a FLAC → IR transcript segments
(brief §5.6 quality upgrade). Imported lazily-safe: importing the module does NOT
download model weights; only WhisperModel(...) instantiation does, which CI mocks."""

from pathlib import Path

from faster_whisper import WhisperModel

from catalog.ingest.ir import ParsedTranscriptSegment


def transcribe_flac(path: str | Path, *, model_size: str = "base") -> tuple[ParsedTranscriptSegment, ...]:
    model = WhisperModel(model_size)
    segments, _info = model.transcribe(str(path))
    return tuple(
        ParsedTranscriptSegment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in segments
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest catalog/tests/test_ingest_transcribe.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/transcribe.py catalog/tests/test_ingest_transcribe.py
git commit -m "feat(ingest): opt-in faster-whisper FLAC transcription helper"
```

---

## Task 6: The matcher — suggest_split + match_recording

**Files:**
- Create: `catalog/ingest/match.py`
- Test: `catalog/tests/test_ingest_match.py`

`match_recording` is agency-agnostic: it receives the candidate `Meeting` rows (the command does the date-window query) and reads only `.pk`, `.start_time`, `.date`. The earlier-by-`start_time` meeting is the committee window; the later is the board window. The split is always a suggestion (`split_confirmed=False`).

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_ingest_match.py`:

```python
import datetime

import pytest

from catalog.ingest.ir import ParsedRecording, ParsedTranscriptSegment
from catalog.ingest.match import CoverageDecision, match_recording, suggest_split
from catalog.models import Jurisdiction, Meeting, Organization


def _seg(start, text):
    return ParsedTranscriptSegment(start=start, end=start + 1, text=text)


def _recording(is_combined, segments=()):
    return ParsedRecording(
        youtube_id="vid",
        title="Committee and Board Meeting 1/19/2023",
        recorded_on=datetime.date(2023, 1, 19),
        upload_date=datetime.date(2023, 1, 20),
        duration_seconds=120,
        source_url="https://youtu.be/vid",
        r2_key="",
        is_combined=is_combined,
        segments=segments,
    )


def test_suggest_split_returns_second_to_order():
    segs = (
        _seg(5.0, "committee meeting call to order"),
        _seg(50.0, "some business"),
        _seg(90.0, "we now come to order"),
    )
    assert suggest_split(segs) == 90.0


def test_suggest_split_none_when_fewer_than_two_markers():
    assert suggest_split((_seg(5.0, "call to order"),)) is None
    assert suggest_split(()) is None


@pytest.fixture
def two_meetings(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    committee = Meeting.objects.create(
        body=body, date=datetime.date(2023, 1, 19), start_time=datetime.time(16, 0),
        kind=Meeting.Kind.COMMITTEE, slug="c-107503",
    )
    board = Meeting.objects.create(
        body=body, date=datetime.date(2023, 1, 19), start_time=datetime.time(18, 30),
        kind=Meeting.Kind.BOARD, slug="b-107593",
    )
    return committee, board


@pytest.mark.django_db
def test_combined_two_meetings_yields_two_windows_with_split(two_meetings):
    committee, board = two_meetings
    rec = _recording(
        is_combined=True,
        segments=(_seg(5.0, "call to order"), _seg(90.0, "come to order")),
    )
    decisions = match_recording(rec, [board, committee])  # order shouldn't matter

    assert decisions == [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=90.0),
        CoverageDecision(meeting_id=board.pk, start_offset=90.0, end_offset=None),
    ]
    assert all(d.split_confirmed is False for d in decisions)


@pytest.mark.django_db
def test_combined_without_split_markers_is_single_window_on_committee(two_meetings):
    committee, board = two_meetings
    rec = _recording(is_combined=True, segments=(_seg(5.0, "no markers here"),))
    decisions = match_recording(rec, [committee, board])
    assert decisions == [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=None)
    ]


@pytest.mark.django_db
def test_single_meeting_one_full_window(two_meetings):
    committee, _ = two_meetings
    rec = _recording(is_combined=False)
    decisions = match_recording(rec, [committee])
    assert decisions == [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=None)
    ]


def test_no_candidate_meetings_is_unlinked():
    rec = _recording(is_combined=True)
    assert match_recording(rec, []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_ingest_match.py -v`
Expected: FAIL — `ModuleNotFoundError: catalog.ingest.match`.

- [ ] **Step 3: Implement `match.py`**

Create `catalog/ingest/match.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_ingest_match.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/match.py catalog/tests/test_ingest_match.py
git commit -m "feat(ingest): recording↔meeting matcher with split suggestion (§6)"
```

---

## Task 7: Migration 0011 — MediaAsset youtube_id unique constraint + TranscriptSegment FTS trigger

**Files:**
- Modify: `catalog/models/media.py` (add the youtube_id constraint to `MediaAsset.Meta`)
- Create: `catalog/migrations/0011_mediaasset_youtube_unique.py` (generated)
- Create: `catalog/migrations/0012_transcriptsegment_search_vector_trigger.py` (hand-written)
- Test: `catalog/tests/test_media.py`

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_media.py`:

```python
import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import IntegrityError

from catalog.models import MediaAsset, Transcript, TranscriptSegment


@pytest.mark.django_db
def test_youtube_id_is_unique_when_present():
    MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="dupid")
    with pytest.raises(IntegrityError):
        MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="dupid")


@pytest.mark.django_db
def test_blank_youtube_id_is_allowed_multiple_times():
    MediaAsset.objects.create(kind=MediaAsset.Kind.AUDIO, youtube_id="")
    MediaAsset.objects.create(kind=MediaAsset.Kind.AUDIO, youtube_id="")  # no error


@pytest.mark.django_db
def test_segment_search_vector_trigger_populates_on_insert():
    media = MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="seg1")
    transcript = Transcript.objects.create(media=media, origin=Transcript.Origin.YOUTUBE_CAPTIONS)
    seg = TranscriptSegment.objects.create(
        transcript=transcript, start=0.0, end=2.0, text="chromebooks for students"
    )
    qs = TranscriptSegment.objects.filter(pk=seg.pk)
    assert qs.filter(search_vector=SearchQuery("chromebooks")).exists()


@pytest.mark.django_db
def test_segment_search_vector_trigger_updates_on_text_change():
    media = MediaAsset.objects.create(kind=MediaAsset.Kind.VIDEO, youtube_id="seg2")
    transcript = Transcript.objects.create(media=media, origin=Transcript.Origin.YOUTUBE_CAPTIONS)
    seg = TranscriptSegment.objects.create(transcript=transcript, start=0.0, end=2.0, text="microsoft")
    seg.text = "lenovo lease"
    seg.save()
    qs = TranscriptSegment.objects.filter(pk=seg.pk)
    assert qs.filter(search_vector=SearchQuery("lenovo")).exists()
    assert not qs.filter(search_vector=SearchQuery("microsoft")).exists()
```

(If `test_media.py` already imports some of these names, dedupe imports rather than duplicating.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_media.py -v -k "youtube_id or segment_search_vector"`
Expected: FAIL — `test_youtube_id_is_unique_when_present` does not raise; the segment-trigger tests find no `search_vector` match.

- [ ] **Step 3: Add the model constraint**

In `catalog/models/media.py`, extend `MediaAsset.Meta.constraints` (keep the existing `uniq_media_r2_key`):

```python
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["r2_key"], condition=~models.Q(r2_key=""), name="uniq_media_r2_key"
            ),
            models.UniqueConstraint(
                fields=["youtube_id"],
                condition=~models.Q(youtube_id=""),
                name="uniq_media_youtube_id",
            ),
        ]
```

- [ ] **Step 4: Generate the constraint migration**

Run: `uv run python manage.py makemigrations catalog --name mediaasset_youtube_unique`
Expected: creates `catalog/migrations/0011_mediaasset_youtube_unique.py` with a single `AddConstraint`.

- [ ] **Step 5: Hand-write the FTS trigger migration**

Create `catalog/migrations/0012_transcriptsegment_search_vector_trigger.py` (mirrors 0010 for `Document`):

```python
from django.db import migrations

_FORWARD = r"""
CREATE OR REPLACE FUNCTION catalog_segment_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('english', coalesce(NEW.text, ''));
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS segment_search_vector_trigger ON catalog_transcriptsegment;
CREATE TRIGGER segment_search_vector_trigger
BEFORE INSERT OR UPDATE ON catalog_transcriptsegment
FOR EACH ROW EXECUTE FUNCTION catalog_segment_search_vector_update();
"""

_REVERSE = r"""
DROP TRIGGER IF EXISTS segment_search_vector_trigger ON catalog_transcriptsegment;
DROP FUNCTION IF EXISTS catalog_segment_search_vector_update();
"""


class Migration(migrations.Migration):
    dependencies = [("catalog", "0011_mediaasset_youtube_unique")]
    operations = [migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE)]
```

- [ ] **Step 6: Run tests + migration check**

Run: `uv run pytest catalog/tests/test_media.py -v`
Expected: PASS (all).
Run: `uv run python manage.py makemigrations --check --dry-run`
Expected: "No changes detected".

- [ ] **Step 7: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/models/media.py catalog/migrations/0011_mediaasset_youtube_unique.py catalog/migrations/0012_transcriptsegment_search_vector_trigger.py catalog/tests/test_media.py
git commit -m "feat(catalog): MediaAsset youtube_id uniqueness + TranscriptSegment FTS trigger"
```

---

## Task 8: Loader — load_recording

**Files:**
- Modify: `catalog/ingest/loader.py`
- Test: `catalog/tests/test_ingest_loader.py`

`load_recording` persists the MediaAsset (idempotent on `youtube_id`), its Transcript + segments, and the MeetingCoverage rows from the matcher's decisions. MediaAsset/Transcript/Segment are evidence (no Citation, not Reviewable). Fail-loud on unknown origin or an unresolvable meeting_id.

- [ ] **Step 1: Write the failing tests**

Append to `catalog/tests/test_ingest_loader.py` (the `context` fixture and imports exist; add the new model + IR imports at the top alongside the existing ones):

```python
# add to the existing `from catalog.ingest.ir import (...)`:  ParsedRecording, ParsedTranscriptSegment
# add to the existing `from catalog.models import (...)`:  MediaAsset, MeetingCoverage, Transcript, TranscriptSegment
from catalog.ingest.match import CoverageDecision
from catalog.ingest.loader import load_recording
from django.contrib.postgres.search import SearchQuery


def _recording(youtube_id="vid1", segments=(ParsedTranscriptSegment(0.0, 2.0, "call to order"),)):
    import datetime

    return ParsedRecording(
        youtube_id=youtube_id,
        title="Committee and Board Meeting 1/19/2023",
        recorded_on=datetime.date(2023, 1, 19),
        upload_date=datetime.date(2023, 1, 20),
        duration_seconds=120,
        source_url="https://youtu.be/vid1",
        r2_key="",
        is_combined=True,
        segments=segments,
        transcript_origin="youtube_captions",
    )


@pytest.mark.django_db
def test_load_recording_creates_asset_transcript_segments(context):
    _, source, _ = context
    media = load_recording(_recording(), [], source=source)
    assert media.youtube_id == "vid1"
    assert media.kind == MediaAsset.Kind.VIDEO
    assert media.recorded_on.isoformat() == "2023-01-19"
    assert media.transcripts.count() == 1
    assert media.transcripts.first().origin == Transcript.Origin.YOUTUBE_CAPTIONS
    assert TranscriptSegment.objects.filter(transcript__media=media).count() == 1


@pytest.mark.django_db
def test_load_recording_populates_segment_fts(context):
    _, source, _ = context
    media = load_recording(
        _recording(segments=(ParsedTranscriptSegment(0.0, 2.0, "chromebooks approved"),)),
        [],
        source=source,
    )
    seg_qs = TranscriptSegment.objects.filter(transcript__media=media)
    assert seg_qs.filter(search_vector=SearchQuery("chromebooks")).exists()


@pytest.mark.django_db
def test_load_recording_creates_coverage_rows(context):
    jur, source, body = context
    import datetime

    committee = Meeting.objects.create(
        body=body, jurisdiction=jur, source=source, source_meeting_id="107503",
        date=datetime.date(2023, 1, 19), start_time=datetime.time(16, 0),
        kind=Meeting.Kind.COMMITTEE, slug="c-107503",
    )
    board = Meeting.objects.create(
        body=body, jurisdiction=jur, source=source, source_meeting_id="107593",
        date=datetime.date(2023, 1, 19), start_time=datetime.time(18, 30),
        kind=Meeting.Kind.BOARD, slug="b-107593",
    )
    decisions = [
        CoverageDecision(meeting_id=committee.pk, start_offset=0.0, end_offset=90.0),
        CoverageDecision(meeting_id=board.pk, start_offset=90.0, end_offset=None),
    ]
    media = load_recording(_recording(), decisions, source=source)
    covs = MeetingCoverage.objects.filter(media=media).order_by("start_offset")
    assert covs.count() == 2
    assert covs[0].meeting == committee and covs[0].start_offset == 0.0 and covs[0].end_offset == 90.0
    assert covs[1].meeting == board and covs[1].end_offset is None
    assert all(c.split_confirmed is False for c in covs)


@pytest.mark.django_db
def test_load_recording_is_idempotent(context):
    _, source, _ = context
    load_recording(_recording(), [], source=source)
    media = load_recording(_recording(), [], source=source)  # re-ingest
    assert MediaAsset.objects.filter(youtube_id="vid1").count() == 1
    assert media.transcripts.count() == 1
    assert TranscriptSegment.objects.filter(transcript__media=media).count() == 1


@pytest.mark.django_db
def test_load_recording_without_segments_creates_no_transcript(context):
    _, source, _ = context
    rec = dataclasses.replace(_recording(), segments=(), transcript_origin="")
    media = load_recording(rec, [], source=source)
    assert media.transcripts.count() == 0


@pytest.mark.django_db
def test_load_recording_unresolvable_meeting_raises(context):
    _, source, _ = context
    decisions = [CoverageDecision(meeting_id=999999, start_offset=0.0, end_offset=None)]
    with pytest.raises(ValueError, match="no Meeting"):
        load_recording(_recording(), decisions, source=source)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -v -k recording`
Expected: FAIL — `ImportError: cannot import name 'load_recording'`.

- [ ] **Step 3: Implement `load_recording`**

Add to the top imports of `catalog/ingest/loader.py`:

```python
from catalog.ingest.ir import ParsedMeeting, ParsedPerson, ParsedRecording
from catalog.ingest.match import CoverageDecision
from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Motion,
    Person,
    Transcript,
    TranscriptSegment,
    Vote,
)
```

Append to `catalog/ingest/loader.py`:

```python
_TRANSCRIPT_ORIGIN = {
    "youtube_captions": Transcript.Origin.YOUTUBE_CAPTIONS,
    "whisper": Transcript.Origin.WHISPER,
}


@transaction.atomic
def load_recording(
    parsed: ParsedRecording, decisions: list[CoverageDecision], *, source
) -> MediaAsset:
    """Persist a recording as evidence: MediaAsset + Transcript + TranscriptSegments
    + MeetingCoverage. No Citations (recordings assert no facts). Idempotent on
    youtube_id: re-ingest wipes the asset's transcripts (cascades segments) and its
    coverage rows, then recreates them."""
    media, _ = MediaAsset.objects.update_or_create(
        youtube_id=parsed.youtube_id,
        defaults={
            "kind": MediaAsset.Kind.VIDEO,
            "r2_key": parsed.r2_key,
            "source_url": parsed.source_url,
            "recorded_on": parsed.recorded_on,
            "upload_date": parsed.upload_date,
            "duration_seconds": parsed.duration_seconds,
            "source": source,
        },
    )

    # Idempotency: wipe transcripts (cascades segments) + coverage before recreating.
    media.transcripts.all().delete()
    media.coverages.all().delete()

    if parsed.segments:
        if parsed.transcript_origin not in _TRANSCRIPT_ORIGIN:
            raise ValueError(f"Unknown transcript origin: {parsed.transcript_origin!r}")
        transcript = Transcript.objects.create(
            media=media,
            language="en",
            origin=_TRANSCRIPT_ORIGIN[parsed.transcript_origin],
        )
        TranscriptSegment.objects.bulk_create(
            [
                TranscriptSegment(
                    transcript=transcript, start=s.start, end=s.end, text=s.text
                )
                for s in parsed.segments
            ]
        )

    for d in decisions:
        meeting = Meeting.objects.filter(pk=d.meeting_id).first()
        if meeting is None:
            raise ValueError(
                f"Coverage decision references no Meeting (pk={d.meeting_id}) for "
                f"recording {parsed.youtube_id!r}."
            )
        MeetingCoverage.objects.create(
            media=media,
            meeting=meeting,
            start_offset=d.start_offset,
            end_offset=d.end_offset,
            split_confirmed=d.split_confirmed,
        )

    return media
```

Note on the bulk_create + FTS trigger: a BEFORE INSERT row trigger fires for each row in a `bulk_create`, so `search_vector` is populated without a per-row save. Do not set `search_vector` in Python.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_ingest_loader.py -v`
Expected: PASS (all, including the pre-existing `load_meeting` tests).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/ingest/loader.py catalog/tests/test_ingest_loader.py
git commit -m "feat(ingest): load_recording — MediaAsset/Transcript/Segments/Coverage (evidence)"
```

---

## Task 9: Management command — ingest_recording

**Files:**
- Create: `catalog/management/commands/ingest_recording.py`
- Test: `catalog/tests/test_ingest_recording_command.py`

The command: resolve/parse the sidecar set; if no `.vtt` and `--whisper`, transcribe the FLAC; query DB meetings within ±3 days of the recording's anchor date; run the matcher; load. `--upload` backfills the `.mp4`/`.flac` to R2 (off by default). Uses a dedicated Source `bcsd-meeting-recordings`.

- [ ] **Step 1: Write the failing tests**

Create `catalog/tests/test_ingest_recording_command.py`:

```python
import datetime
import shutil
from pathlib import Path

import pytest
from django.core.management import call_command

from catalog.models import (
    Jurisdiction,
    MediaAsset,
    Meeting,
    MeetingCoverage,
    Organization,
    Source,
    TranscriptSegment,
)

FIX = Path("catalog/tests/fixtures/recordings/BCSD_MEETING_RECORDINGS")
INFO_NAME = "test_committee_and_board_1_19_2023_TESTvideo01_.info.json"


@pytest.fixture
def boe(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bibb-county-boe")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    return jur, body


@pytest.mark.django_db
def test_command_combined_creates_two_coverage_windows(boe):
    jur, body = boe
    committee = Meeting.objects.create(
        body=body, jurisdiction=jur, date=datetime.date(2023, 1, 19),
        start_time=datetime.time(16, 0), kind=Meeting.Kind.COMMITTEE, slug="c",
    )
    board = Meeting.objects.create(
        body=body, jurisdiction=jur, date=datetime.date(2023, 1, 19),
        start_time=datetime.time(18, 30), kind=Meeting.Kind.BOARD, slug="b",
    )
    call_command("ingest_recording", str(FIX / INFO_NAME))

    media = MediaAsset.objects.get(youtube_id="TESTvideo01")
    assert TranscriptSegment.objects.filter(transcript__media=media).exists()
    covs = MeetingCoverage.objects.filter(media=media).order_by("start_offset")
    assert covs.count() == 2
    assert covs[0].meeting == committee and covs[0].start_offset == 0.0
    assert covs[1].meeting == board and covs[1].end_offset is None
    assert covs[0].end_offset == covs[1].start_offset  # the split offset
    assert Source.objects.filter(slug="bcsd-meeting-recordings").exists()


@pytest.mark.django_db
def test_command_no_matching_meeting_is_unlinked(boe):
    # No Meeting rows on the recording date → unlinked MediaAsset, zero coverage.
    call_command("ingest_recording", str(FIX / INFO_NAME))
    media = MediaAsset.objects.get(youtube_id="TESTvideo01")
    assert MeetingCoverage.objects.filter(media=media).count() == 0


@pytest.mark.django_db
def test_command_whisper_used_when_no_vtt(boe, tmp_path, monkeypatch):
    # Stage an info.json with no sibling .vtt.
    info = tmp_path / "novtt_WHISPERvid1_.info.json"
    info.write_text(
        '{"id": "WHISPERvid1", "title": "Board Meeting 5/5/2023", '
        '"duration": 30, "upload_date": "20230506", "webpage_url": "https://youtu.be/WHISPERvid1"}'
    )
    from catalog.ingest.ir import ParsedTranscriptSegment

    monkeypatch.setattr(
        "catalog.management.commands.ingest_recording.transcribe_flac",
        lambda path, **kw: (ParsedTranscriptSegment(0.0, 1.0, "whispered text"),),
    )
    # Also stage a fake .flac so the command finds something to transcribe.
    (tmp_path / "novtt_WHISPERvid1_.flac").write_bytes(b"\x00")

    call_command("ingest_recording", str(info), "--whisper")
    media = MediaAsset.objects.get(youtube_id="WHISPERvid1")
    seg = TranscriptSegment.objects.get(transcript__media=media)
    assert seg.text == "whispered text"
    assert media.transcripts.first().origin == media.transcripts.first().Origin.WHISPER
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest catalog/tests/test_ingest_recording_command.py -v`
Expected: FAIL — `CommandError: Unknown command: 'ingest_recording'`.

- [ ] **Step 3: Implement the command**

Create `catalog/management/commands/ingest_recording.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest catalog/tests/test_ingest_recording_command.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Full suite + checks**

Run: `uv run pytest -q`
Expected: all passing (119 prior + the new tests).
Run: `uv run python manage.py check` → no issues.
Run: `uv run python manage.py makemigrations --check --dry-run` → No changes.

- [ ] **Step 6: Lint + commit**

```bash
uv run ruff check . && uv run ruff format --check .
git add catalog/management/commands/ingest_recording.py catalog/tests/test_ingest_recording_command.py
git commit -m "feat(ingest): ingest_recording management command (Source B)"
```

---

## Task 10: Docs — update HANDOFF + manual smoke instructions

**Files:**
- Modify: `docs/superpowers/HANDOFF.md`

- [ ] **Step 1: Update the handoff**

Edit `docs/superpowers/HANDOFF.md`:
- Mark slice 1d as complete (mirror the 1b/1c "COMPLETE" blocks): list shipped modules (`bcsd/vtt.py`, `bcsd/recording.py`, `transcribe.py`, `match.py`, `load_recording`, `ingest_recording`, migrations 0011/0012), the 2023-01-19 anchor pivot, the locked scope decisions, and the new test count from `uv run pytest -q`.
- Add a "Deferred from slice 1d" list: multi-upload duplicate primary-selection / matcher-at-scale (Phase 2); faster-whisper as a default quality pass; admin split-confirm scrubber UI (Phase 1e/4); the transcript→video deep-link UI + segment search (slice 1e).
- Point "Immediate next task" at **slice 1e** (the public read UI) per the roadmap.
- Update the start-of-session checklist's expected pass count.

- [ ] **Step 2: Record the manual smoke test (run it, capture real numbers)**

This is a real verification step, not just docs. With `docker compose up -d db` and a populated dev DB:

```bash
# 1. Ingest the 2023-01-19 committee + board meeting folders (Source A) first.
uv run python manage.py ingest_bcsd \
  archive_data/bcsd/BCSD_BOE_MEETINGS/2023/01/2023-01-19_1600_committee-meeting_mid-107503
uv run python manage.py ingest_bcsd \
  archive_data/bcsd/BCSD_BOE_MEETINGS/2023/01/2023-01-19_1830_board-meeting_mid-107593

# 2. Ingest the combined recording (Source B) and watch the matcher split it.
uv run python manage.py ingest_recording \
  "archive_data/bcsd/BCSD_MEETING_RECORDINGS/2023-01-20-Bibb_County_Board_of_Education_Committee_and_Board_Meeting_1_19_2023_CWjfBn10EJc_.info.json"
```

Expected: 1 MediaAsset, several thousand deduped segments, **2** coverage windows, a non-null split offset (~ the second "call to order", roughly the recording midpoint), both `split_confirmed=False`. Record the actual numbers in the HANDOFF "Real-archive smoke test" line. Then sanity-check the unlinked branch against a non-meeting video (a "Show Up Program" `.info.json`) → 0 coverage windows.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/HANDOFF.md
git commit -m "docs: mark slice 1d complete; point handoff at slice 1e"
```

---

## Final: whole-branch review + merge

After all tasks: run the full gate (`uv run pytest -q`, `manage.py check`, `makemigrations --check --dry-run`, `ruff check`/`format --check`), then a final whole-branch review (per subagent-driven-development), apply any agreed fixes, merge `feat/1d-recordings` → `main`, and push `main` (pushing is expected for this project).

---

## Self-review notes (coverage of the spec)

- §VTT dedup → Task 3. §sidecar/info.json/title-date/combined/r2_key → Task 4. §faster-whisper (opt-in, mocked) → Task 5 + the `--whisper` path in Task 9. §matcher branches (2-window+split, 1-window, unlinked, <2-marker fallback) → Task 6 + Task 9 E2E. §FTS trigger + idempotency key → Task 7. §load_recording (evidence, idempotent, fail-loud) → Task 8. §command (`--whisper`, `--upload`, dedicated Source, date-window query) → Task 9. §manual smoke + deferred scope + handoff → Task 10. §provenance (no Citations; not Reviewable) → enforced by Task 8 (no Citation creation) and verified implicitly (no Reviewable on these models).
- Type consistency: `ParsedRecording`/`ParsedTranscriptSegment` fields, `CoverageDecision(meeting_id, start_offset, end_offset, split_confirmed)`, `match_recording(parsed, candidate_meetings)`, `load_recording(parsed, decisions, *, source)`, `transcribe_flac(path, *, model_size)`, `parse_vtt(text)`, `parse_recording(info_path)`, `parse_title_date(title)` are used consistently across tasks.
