import pytest
from django.core.management import call_command

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
