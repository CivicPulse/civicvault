from unittest import mock

from django.core.files.storage import FileSystemStorage

from catalog.ingest import storage


def test_upload_missing_skips_when_object_exists(tmp_path):
    local = tmp_path / "a.pdf"
    local.write_bytes(b"%PDF-1.4 x")
    fake = mock.Mock()
    fake.exists.return_value = True
    with mock.patch.object(storage, "default_storage", fake):
        uploaded = storage.upload_missing("BCSD/x/a.pdf", str(local))
    assert uploaded is False
    fake.save.assert_not_called()


def test_upload_missing_uploads_when_absent(tmp_path):
    local = tmp_path / "a.pdf"
    local.write_bytes(b"%PDF-1.4 x")
    fake = mock.Mock()
    fake.exists.return_value = False
    with mock.patch.object(storage, "default_storage", fake):
        uploaded = storage.upload_missing("BCSD/x/a.pdf", str(local))
    assert uploaded is True
    assert fake.save.call_count == 1
    assert fake.save.call_args[0][0] == "BCSD/x/a.pdf"


def test_upload_missing_noops_on_filesystem_backend(tmp_path):
    local = tmp_path / "a.pdf"
    local.write_bytes(b"%PDF-1.4 x")
    fs = FileSystemStorage(location=str(tmp_path / "store"))
    with mock.patch.object(storage, "default_storage", fs):
        uploaded = storage.upload_missing("BCSD/x/a.pdf", str(local))
    assert uploaded is False  # never writes when storage is the local fallback
