"""Opt-in faster-whisper transcription of a FLAC → IR transcript segments
(brief §5.6 quality upgrade). Imported lazily-safe: importing the module does NOT
download model weights; only WhisperModel(...) instantiation does, which CI mocks."""

from pathlib import Path

from faster_whisper import WhisperModel

from catalog.ingest.ir import ParsedTranscriptSegment


def transcribe_flac(
    path: str | Path, *, model_size: str = "base"
) -> tuple[ParsedTranscriptSegment, ...]:
    model = WhisperModel(model_size)
    segments, _info = model.transcribe(str(path))
    return tuple(
        ParsedTranscriptSegment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in segments
    )
