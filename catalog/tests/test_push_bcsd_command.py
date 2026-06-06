import io
import urllib.error

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from catalog.management.commands import push_bcsd

# Reuse the folder-staging helper from the existing command test.
from catalog.tests.test_ingest_bcsd_command import _stage_pair

COMMITTEE = "2025-04-17_1600_committee-meeting_mid-124789"


@pytest.mark.django_db
def test_push_bcsd_uploads_then_posts(monkeypatch, tmp_path):
    posted = {}
    put_urls = []

    def fake_post(url, token, payload):
        if url.endswith("/uploads"):
            # Presign every requested key.
            return 200, {
                "uploads": [
                    {"key": k, "url": f"https://r2/{k}", "expires_in": 3600}
                    for k in payload["keys"]
                ],
                "skipped": [],
            }
        posted["url"] = url
        posted["payload"] = payload
        return 201, {"source_meeting_id": payload["source_meeting_id"], "votes": 0}

    def fake_put(url, path):
        put_urls.append(url)
        return 200

    monkeypatch.setattr(push_bcsd, "_post", fake_post)
    monkeypatch.setattr(push_bcsd, "_put_file", fake_put)

    root = _stage_pair(tmp_path)
    call_command(
        "push_bcsd",
        str(root / COMMITTEE),
        "--api-base",
        "https://vault.example",
        "--token",
        "t",
    )

    assert posted["url"] == "https://vault.example/api/v1/meetings"
    assert posted["payload"]["source_meeting_id"]
    # The committee folder's hmh.pdf attachment was uploaded via a presigned PUT.
    assert any("hmh.pdf" in u for u in put_urls)


def test_post_returns_status_and_body_on_http_error(monkeypatch):
    def raise_http_error(req):
        raise urllib.error.HTTPError(
            req.full_url,
            409,
            "Conflict",
            hdrs=None,
            fp=io.BytesIO(b'{"detail": "has reviewed facts"}'),
        )

    monkeypatch.setattr(push_bcsd.urllib.request, "urlopen", raise_http_error)
    status, body = push_bcsd._post("https://x/api/v1/meetings", "t", {"a": 1})
    assert status == 409
    assert body["detail"] == "has reviewed facts"


@pytest.mark.django_db
def test_no_upload_skips_uploads(monkeypatch, tmp_path):
    put_urls = []
    posted = {}

    def fake_post(url, token, payload):
        posted["url"] = url
        return 201, {"source_meeting_id": payload["source_meeting_id"]}

    monkeypatch.setattr(push_bcsd, "_post", fake_post)
    monkeypatch.setattr(push_bcsd, "_put_file", lambda url, path: put_urls.append(url))

    root = _stage_pair(tmp_path)
    call_command(
        "push_bcsd",
        str(root / COMMITTEE),
        "--api-base",
        "https://vault.example",
        "--token",
        "t",
        "--no-upload",
    )
    assert put_urls == []
    assert posted["url"] == "https://vault.example/api/v1/meetings"


def test_missing_credentials_raises(monkeypatch, tmp_path):
    # Defaults pull from the env; clear them so the guard is deterministic.
    monkeypatch.delenv("INGEST_API_TOKEN", raising=False)
    monkeypatch.delenv("INGEST_API_BASE", raising=False)
    root = _stage_pair(tmp_path)
    with pytest.raises(CommandError):
        call_command("push_bcsd", str(root / COMMITTEE), "--api-base", "https://x")
