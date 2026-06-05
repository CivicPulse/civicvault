"""Opt-in faster-whisper transcription of a FLAC → IR transcript segments
(brief §5.6 quality upgrade). Imported lazily-safe: importing the module does NOT
download model weights; only WhisperModel(...) instantiation does, which CI mocks."""

import ctypes
import glob
import sysconfig
from functools import cache
from pathlib import Path

from faster_whisper import WhisperModel

from catalog.ingest.ir import ParsedTranscriptSegment


@cache
def _preload_cuda_runtime() -> None:
    """Make the pip-installed CUDA 12 libs (the `gpu` dependency-group's
    nvidia-*-cu12 wheels) loadable by CTranslate2 — no system CUDA, no
    LD_LIBRARY_PATH.

    The wheels drop their .so files under site-packages/nvidia/*/lib, which is not
    on the dynamic loader's search path. Preloading each one (RTLD_GLOBAL,
    dependency order first) registers it by soname, so CTranslate2's later bare
    dlopen of e.g. "libcublas.so.12" resolves to the already-loaded object instead
    of searching the filesystem. A no-op when the wheels are absent (CPU-only box
    or CI) — transcribe_flac then falls back to CPU. @cache: runs once per process.
    """
    sp = sysconfig.get_paths()["purelib"]
    for rel in (
        "nvidia/cublas/lib/libcublasLt.so.12",
        "nvidia/cublas/lib/libcublas.so.12",
        "nvidia/cuda_nvrtc/lib/libnvrtc.so.12",
        "nvidia/cudnn/lib/libcudnn.so.9",
        "nvidia/cudnn/lib/libcudnn_*.so.9",  # cuDNN engine sublibs
    ):
        for path in sorted(glob.glob(f"{sp}/{rel}")):
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass  # not standalone-loadable; CT2 resolves it via the ones above


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
    _preload_cuda_runtime()  # register the gpu-group CUDA libs if present (else no-op)
    try:
        # Default device 'auto' uses the GPU when its CUDA runtime is loadable.
        return _segments(WhisperModel(model_size), path)
    except Exception:
        # A GPU can be present while its CUDA libs (libcublas/cuDNN) are missing;
        # 'auto' then picks CUDA and fails at transcribe time. CPU needs no CUDA
        # runtime, so retry there — slower, but it always works.
        return _segments(WhisperModel(model_size, device="cpu", compute_type="int8"), path)
