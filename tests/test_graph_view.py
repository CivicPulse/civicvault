"""Tests for the relationship graph view (core:graph).

The load-bearing guarantee is the review gate: Person and Organization are
Reviewable, so only reviewed=True entities — and reviewed facts — may appear in
the public graph. These tests pin that, plus the basic node/edge shape and the
provenance link on a meeting's documents.
"""

import datetime
import json
import re

import pytest

from catalog.models import (
    AgendaItem,
    Appearance,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Vote,
)

GRAPH_DATA_RE = re.compile(
    r'id="graph-data" type="application/json">(.*?)</script>', re.S
)


def _graph_payload(client):
    resp = client.get("/graph/")
    assert resp.status_code == 200
    body = resp.content.decode()
    match = GRAPH_DATA_RE.search(body)
    assert match, "graph-data json_script block missing from response"
    return resp, json.loads(match.group(1))


@pytest.fixture
def seeded(db):
    """A minimal but representative graph with one reviewed and one unreviewed
    person, so the gate has something to exclude."""
    jur = Jurisdiction.objects.create(
        name="Bibb County BOE", slug="bibb", kind=Jurisdiction.Kind.SCHOOL_DISTRICT
    )
    body = Organization.objects.create(
        name="Board of Education", slug="boe", jurisdiction=jur, reviewed=True
    )
    Organization.objects.create(name="Shadow Vendor", slug="shadow", reviewed=False)
    meeting = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 4, 17),
        kind=Meeting.Kind.BOARD,
        slug="m1",
    )
    item = AgendaItem.objects.create(meeting=meeting, order=1, title="Budget")

    shown = Person.objects.create(full_name="Henry Ficklin", slug="henry", reviewed=True)
    hidden = Person.objects.create(full_name="Jane Doe", slug="jane", reviewed=False)

    # Reviewed facts tie the reviewed person to the meeting.
    Appearance.objects.create(person=shown, meeting=meeting, reviewed=True)
    Vote.objects.create(person=shown, agenda_item=item, value=Vote.Value.YEA, reviewed=True)
    # An unreviewed vote for the hidden person — must not leak an edge.
    Vote.objects.create(person=hidden, agenda_item=item, value=Vote.Value.NAY, reviewed=False)

    Document.objects.create(
        title="Budget Packet",
        meeting=meeting,
        access_level=Document.AccessLevel.PUBLIC,
        source_url="https://example.org/budget.pdf",
    )
    return {"jur": jur, "body": body, "meeting": meeting, "shown": shown, "hidden": hidden}


@pytest.mark.django_db
def test_graph_renders_and_embeds_payload(client, seeded):
    _resp, data = _graph_payload(client)
    assert {"nodes", "edges"} <= data.keys()
    ids = {n["id"] for n in data["nodes"]}
    assert f"jurisdiction-{seeded['jur'].pk}" in ids
    assert f"organization-{seeded['body'].pk}" in ids
    assert f"meeting-{seeded['meeting'].pk}" in ids


@pytest.mark.django_db
def test_reviewed_person_is_a_node(client, seeded):
    _resp, data = _graph_payload(client)
    ids = {n["id"] for n in data["nodes"]}
    assert f"person-{seeded['shown'].pk}" in ids


@pytest.mark.django_db
def test_unreviewed_entities_are_gated_out(client, seeded):
    """The core product principle: nothing reviewed=False reaches the public."""
    _resp, data = _graph_payload(client)
    ids = {n["id"] for n in data["nodes"]}
    labels = {n["label"] for n in data["nodes"]}
    assert f"person-{seeded['hidden'].pk}" not in ids
    assert "Jane Doe" not in labels
    assert "Shadow Vendor" not in labels


@pytest.mark.django_db
def test_no_edge_from_unreviewed_vote(client, seeded):
    _resp, data = _graph_payload(client)
    hidden_id = f"person-{seeded['hidden'].pk}"
    touching_hidden = [
        e for e in data["edges"] if hidden_id in (e["source"], e["target"])
    ]
    assert touching_hidden == []


@pytest.mark.django_db
def test_reviewed_person_meeting_edge_exists(client, seeded):
    _resp, data = _graph_payload(client)
    person_id = f"person-{seeded['shown'].pk}"
    meeting_id = f"meeting-{seeded['meeting'].pk}"
    pairs = {(e["source"], e["target"]) for e in data["edges"]}
    assert (person_id, meeting_id) in pairs


@pytest.mark.django_db
def test_meeting_node_carries_document_source_link(client, seeded):
    _resp, data = _graph_payload(client)
    meeting = next(
        n for n in data["nodes"] if n["id"] == f"meeting-{seeded['meeting'].pk}"
    )
    assert meeting["docs"], "meeting node should surface its documents"
    assert any("/source/" in d["href"] for d in meeting["docs"])


@pytest.mark.django_db
def test_empty_corpus_renders_without_error(client, db):
    resp, data = _graph_payload(client)
    assert resp.status_code == 200
    assert data["nodes"] == []
    assert data["edges"] == []
