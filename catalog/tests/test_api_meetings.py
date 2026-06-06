import datetime
import json
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from catalog.api.serializers import payload_from_meeting
from catalog.ingest.ir import (
    ParsedAgendaItem,
    ParsedMeeting,
    ParsedPerson,
    ParsedVote,
)
from catalog.models import Vote

TOKEN = "s3cret-ingest-token"


def _client(settings):
    settings.INGEST_API_TOKEN = TOKEN
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return c


def _wire(parsed):
    return json.loads(json.dumps(payload_from_meeting(parsed), default=str))


def _meeting(source_meeting_id="mid-1"):
    voter = ParsedPerson(full_name="Lisa Garrett-Boyd", raw_name="Ms. Garrett-Boyd")
    item = ParsedAgendaItem(
        order=1,
        code="A-1",
        title="Adopt",
        item_type="action",
        reading_stage="",
        section="V",
        outcome_status="passed",
        amount=Decimal("100.00"),
        votes=(ParsedVote(person=voter, value="yea"),),
    )
    return ParsedMeeting(
        date=datetime.date(2025, 1, 9),
        start_time=None,
        kind_slug="board",
        source_meeting_id=source_meeting_id,
        source_url="https://x",
        source_path="/m",
        folder_name="f",
        title="Board Meeting",
        agenda_items=(item,),
    )


@pytest.mark.django_db
def test_post_meeting_creates_unreviewed_proposals(settings):
    resp = _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["source_meeting_id"] == "mid-1"
    assert body["votes"] == 1
    assert body["reviewed"] is False
    assert Vote.objects.filter(reviewed=False).count() == 1


@pytest.mark.django_db
def test_repost_unreviewed_meeting_succeeds(settings):
    client = _client(settings)
    client.post("/api/v1/meetings", _wire(_meeting()), format="json")
    resp = client.post("/api/v1/meetings", _wire(_meeting()), format="json")
    assert resp.status_code == 201


@pytest.mark.django_db
def test_repost_over_reviewed_fact_conflicts(settings):
    _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    Vote.objects.update(reviewed=True)  # simulate admin review
    resp = _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    assert resp.status_code == 409


@pytest.mark.django_db
def test_force_overrides_reviewed_conflict(settings):
    _client(settings).post("/api/v1/meetings", _wire(_meeting()), format="json")
    Vote.objects.update(reviewed=True)
    payload = _wire(_meeting())
    payload["force"] = True
    resp = _client(settings).post("/api/v1/meetings", payload, format="json")
    assert resp.status_code == 201
    assert Vote.objects.filter(reviewed=False).count() == 1  # wiped & recreated


@pytest.mark.django_db
def test_bad_vote_value_returns_422(settings):
    payload = _wire(_meeting())
    payload["agenda_items"][0]["votes"][0]["value"] = "maybe"
    resp = _client(settings).post("/api/v1/meetings", payload, format="json")
    assert resp.status_code == 422
