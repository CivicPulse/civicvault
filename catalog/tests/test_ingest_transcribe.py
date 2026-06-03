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
