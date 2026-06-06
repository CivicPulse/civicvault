import pytest
from rest_framework.test import APIClient

from catalog.api import uploads as uploads_mod

TOKEN = "s3cret-ingest-token"


def _client(settings):
    settings.INGEST_API_TOKEN = TOKEN
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return c


@pytest.mark.django_db
def test_uploads_requires_auth(settings):
    settings.INGEST_API_TOKEN = TOKEN
    resp = APIClient().post("/api/v1/uploads", {"keys": ["a"]}, format="json")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_uploads_503_without_remote_storage(settings):
    # Simulate no R2 bucket configured (filesystem fallback → no remote storage).
    settings.R2_BUCKET = ""
    resp = _client(settings).post("/api/v1/uploads", {"keys": ["a"]}, format="json")
    assert resp.status_code == 503


@pytest.mark.django_db
def test_uploads_presigns_missing_and_skips_present(settings, monkeypatch):
    # Drive the real remote_storage_available() via the setting it reads — the
    # view imports the name at module load, so monkeypatching uploads_mod won't
    # rebind the view's reference. A truthy R2_BUCKET makes it return True in any
    # environment (CI has no R2_BUCKET; this dev box does — don't rely on either).
    settings.R2_BUCKET = "civicvault-media"

    class _Storage:
        def exists(self, key):
            return key == "present.pdf"

    class _S3:
        def generate_presigned_url(self, op, Params, ExpiresIn):
            return f"https://r2.example/{Params['Key']}?sig=1"

    monkeypatch.setattr(uploads_mod, "default_storage", _Storage())
    monkeypatch.setattr(uploads_mod, "_client", lambda: _S3())

    resp = _client(settings).post(
        "/api/v1/uploads", {"keys": ["missing.pdf", "present.pdf"]}, format="json"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["skipped"] == ["present.pdf"]
    assert len(body["uploads"]) == 1
    assert body["uploads"][0]["key"] == "missing.pdf"
    assert body["uploads"][0]["url"].startswith("https://r2.example/missing.pdf")
