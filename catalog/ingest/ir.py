"""Adapter contract: framework-neutral parsed records (brief §14.3).

Every ingestion adapter emits these dataclasses; the generic loader consumes
them. Intentionally NO Django imports so parsers stay pure and unit-testable.
String enum values mirror the model TextChoices values (e.g. "yea", "action",
"unanimous") so the loader maps them with a plain lookup.
"""

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedPerson:
    """A person mention. `full_name` is normalized; `raw_name` is verbatim source."""

    full_name: str
    raw_name: str
    role_hint: str = ""  # trailing roster role, e.g. "President"


@dataclass(frozen=True)
class ParsedVote:
    person: ParsedPerson
    value: str  # "yea" | "nay" | "abstain" | "absent"


@dataclass(frozen=True)
class ParsedMotion:
    kind: str  # "simple" | "initial" | "amended"
    sequence: int
    moved_by: ParsedPerson | None
    seconded_by: ParsedPerson | None
    result_text: str
    status: str  # "passed" | "failed" | "unanimous" | "none"


@dataclass(frozen=True)
class ParsedAppearance:
    person: ParsedPerson
    role: str  # "member" | "invocation" | "pledge" | "speaker" | "presenter" | "staff"


@dataclass(frozen=True)
class ParsedAgendaItem:
    order: int
    code: str
    title: str
    item_type: str  # "action" | "presentation" | "information" | "other"
    reading_stage: str  # "first" | "second" | ""
    section: str
    outcome_text: str = ""
    outcome_status: str = "none"
    motions: tuple[ParsedMotion, ...] = ()
    votes: tuple[ParsedVote, ...] = ()
    file_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedDocument:
    kind: str  # "minutes" | "agenda" | "other" | attachment heuristics (policy/memo/presentation)
    title: str
    source_path: str
    text: str
    # Attachment fields (defaults keep the existing .md source-doc call sites working).
    r2_key: str = ""
    ocr_status: str = "unknown"  # "has_text" | "ocr_needed" | "empty" | "unknown"
    agenda_item_code: str | None = None  # None → meeting-level (no AgendaItem link)
    is_attachment: bool = False


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


@dataclass(frozen=True)
class ParsedMeeting:
    date: datetime.date
    start_time: datetime.time | None
    kind_slug: str
    source_meeting_id: str
    source_url: str
    source_path: str
    folder_name: str
    title: str
    roster: tuple[ParsedPerson, ...] = ()
    agenda_items: tuple[ParsedAgendaItem, ...] = ()
    appearances: tuple[ParsedAppearance, ...] = ()  # invocation/pledge/visitors (NOT roster)
    has_minutes: bool = False
    raw_documents: tuple[ParsedDocument, ...] = ()
