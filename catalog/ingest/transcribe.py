"""Opt-in faster-whisper transcription of a FLAC → IR transcript segments
(brief §5.6 quality upgrade). Imported lazily-safe: importing the module does NOT
download model weights; only WhisperModel(...) instantiation does, which CI mocks."""

from pathlib import Path

from faster_whisper import WhisperModel

from catalog.ingest.ir import ParsedTranscriptSegment


def _segments(model: WhisperModel, path: str | Path) -> tuple[ParsedTranscriptSegment, ...]:
    # transcribe() returns a lazy generator; the tuple() forces it to run, so a
    # backend (e.g. CUDA) error surfaces here inside the caller's try.
    segments, _info = model.transcribe(str(path))
    return tuple(
        ParsedTranscriptSegment(start=float(s.start), end=float(s.end), text=s.text.strip())
        for s in segments
    )


def transcribe_flac(
    path: str | Path, *, model_size: str = "base"
) -> tuple[ParsedTranscriptSegment, ...]:
    try:
        # Default device 'auto' uses the GPU when its CUDA runtime is loadable.
        return _segments(WhisperModel(model_size), path)
    except Exception:
        # A GPU can be present while its CUDA libs (libcublas/cuDNN) are missing;
        # 'auto' then picks CUDA and fails at transcribe time. CPU needs no CUDA
        # runtime, so retry there — slower, but it always works.
        return _segments(WhisperModel(model_size, device="cpu", compute_type="int8"), path)
