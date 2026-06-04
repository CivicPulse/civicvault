"""Tests for the relationship graph view (core:graph).

The load-bearing guarantee is the review gate: Person and Organization are
Reviewable, so only reviewed=True entities — and reviewed facts — may appear in
the public graph. These tests pin that, plus the topology: people link directly
to a body (not via meeting nodes), and the meetings ride along as the edge's
payload.
"""

import datetime
import json
import re
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType

from catalog.models import (
    AgendaItem,
    Appearance,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Relationship,
    Vote,
)


def _make_relationship(subject, obj, predicate, **kwargs):
    """Create a directed Relationship between two model instances."""
    return Relationship.objects.create(
        subject_ct=ContentType.objects.get_for_model(subject),
        subject_id=subject.pk,
        object_ct=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        predicate=predicate,
        **kwargs,
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

    # A second meeting of the same body, so the two ties must collapse into one
    # person<->body edge carrying both meetings.
    meeting2 = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 2, 20),
        kind=Meeting.Kind.COMMITTEE,
        slug="m2",
    )

    # Reviewed facts tie the reviewed person to both meetings of the body.
    Appearance.objects.create(
        person=shown, meeting=meeting, reviewed=True, role=Appearance.Role.MEMBER
    )
    Appearance.objects.create(
        person=shown, meeting=meeting2, reviewed=True, role=Appearance.Role.MEMBER
    )
    Vote.objects.create(person=shown, agenda_item=item, value=Vote.Value.YEA, reviewed=True)
    # An unreviewed vote for the hidden person — must not leak an edge.
    Vote.objects.create(person=hidden, agenda_item=item, value=Vote.Value.NAY, reviewed=False)

    Document.objects.create(
        title="Budget Packet",
        meeting=meeting,
        access_level=Document.AccessLevel.PUBLIC,
        source_url="https://example.org/budget.pdf",
    )
    return {
        "jur": jur,
        "body": body,
        "meeting": meeting,
        "meeting2": meeting2,
        "shown": shown,
        "hidden": hidden,
    }


@pytest.mark.django_db
def test_graph_renders_and_embeds_payload(client, seeded):
    _resp, data = _graph_payload(client)
    assert {"nodes", "edges"} <= data.keys()
    ids = {n["id"] for n in data["nodes"]}
    assert f"jurisdiction-{seeded['jur'].pk}" in ids
    assert f"organization-{seeded['body'].pk}" in ids


@pytest.mark.django_db
def test_meetings_are_not_nodes(client, seeded):
    """Meetings are evidence on the person<->body edge, not graph nodes."""
    _resp, data = _graph_payload(client)
    ids = {n["id"] for n in data["nodes"]}
    assert not any(i.startswith("meeting-") for i in ids)
    assert "meeting" not in {n["type"] for n in data["nodes"]}


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
def test_person_links_directly_to_body_with_collapsed_meetings(client, seeded):
    """One person<->body edge per pair, carrying every shared meeting as payload."""
    _resp, data = _graph_payload(client)
    person_id = f"person-{seeded['shown'].pk}"
    org_id = f"organization-{seeded['body'].pk}"
    ties = [e for e in data["edges"] if {e["source"], e["target"]} == {person_id, org_id}]
    assert len(ties) == 1, "the two meeting ties must collapse into a single edge"
    edge = ties[0]
    assert edge["kind"] == "participates"  # no board_member_of relationship yet
    assert len(edge["rows"]) == 2
    # newest meeting first (Apr 17 before Feb 20)
    assert edge["rows"][0]["label"].startswith("Apr")
    # the board meeting where the person voted carries that in its note
    assert any("voted" in m["note"] for m in edge["rows"])


@pytest.mark.django_db
def test_person_node_has_no_meeting_edges(client, seeded):
    """A person's only edges are to bodies, never to meetings."""
    _resp, data = _graph_payload(client)
    person_id = f"person-{seeded['shown'].pk}"
    for e in data["edges"]:
        for end in (e["source"], e["target"]):
            if end == person_id:
                other = e["target"] if e["source"] == person_id else e["source"]
                assert other.startswith("organization-")


@pytest.mark.django_db
def test_empty_corpus_renders_without_error(client, db):
    resp, data = _graph_payload(client)
    assert resp.status_code == 200
    assert data["nodes"] == []
    assert data["edges"] == []


@pytest.mark.django_db
def test_search_and_filter_controls_render(client, seeded):
    """The toolbar ships the search input + clear control and the list carries
    the data hooks the client JS filters on."""
    body = client.get("/graph/").content.decode()
    assert 'id="graph-q"' in body
    assert "data-graph-clear" in body
    assert "data-graph-empty-search" in body
    assert "data-list-empty" in body
    assert "data-node-id=" in body
    assert "data-group" in body


@pytest.mark.django_db
def test_list_edges_carry_endpoint_types_for_filtering(client, seeded):
    """Each relationship row exposes both endpoint types so type filters can hide
    edges in the List view exactly as in the graph."""
    body = client.get("/graph/").content.decode()
    assert "data-edge" in body
    # the person->body tie should expose both endpoint types
    assert 'data-source-type="person"' in body
    assert 'data-target-type="body"' in body


@pytest.mark.django_db
def test_board_member_relationship_relabels_the_edge(client, seeded):
    """A reviewed board_member_of relationship turns the participation edge into a
    typed 'board member' tie."""
    _make_relationship(
        seeded["shown"],
        seeded["body"],
        Relationship.Predicate.BOARD_MEMBER_OF,
        reviewed=True,
    )
    _resp, data = _graph_payload(client)
    pid = f"person-{seeded['shown'].pk}"
    oid = f"organization-{seeded['body'].pk}"
    edge = next(e for e in data["edges"] if {e["source"], e["target"]} == {pid, oid})
    assert edge["kind"] == "board_member"
    assert edge["label"] == "board member"


@pytest.mark.django_db
def test_contract_relationship_adds_vendor_node_and_money_edge(client, seeded):
    """A reviewed contracts_with relationship adds a vendor node and a directed,
    dollar-summed edge whose rows carry the amount."""
    vendor = Organization.objects.create(
        name="Acme Copiers", slug="acme", kind=Organization.Kind.COMPANY, reviewed=True
    )
    _make_relationship(
        seeded["body"],
        vendor,
        Relationship.Predicate.CONTRACTS_WITH,
        amount=Decimal("125000.00"),
        note="Copier lease",
        reviewed=True,
    )
    _resp, data = _graph_payload(client)
    vnode = next((n for n in data["nodes"] if n["id"] == f"organization-{vendor.pk}"), None)
    assert vnode is not None and vnode["type"] == "vendor"
    edge = next(e for e in data["edges"] if e["kind"] == "contracts_with")
    assert edge["source"] == f"organization-{seeded['body'].pk}"
    assert edge["target"] == f"organization-{vendor.pk}"
    assert "$125,000" in edge["label"]
    assert edge["rows"][0]["note"] == "$125,000"


@pytest.mark.django_db
def test_unreviewed_relationship_and_vendor_are_gated(client, seeded):
    """Unreviewed vendor + relationship stay out of the public graph."""
    vendor = Organization.objects.create(
        name="Hidden Vendor", slug="hidden-vendor", kind=Organization.Kind.COMPANY, reviewed=False
    )
    _make_relationship(
        seeded["body"],
        vendor,
        Relationship.Predicate.CONTRACTS_WITH,
        amount=Decimal("999.00"),
        reviewed=False,
    )
    _resp, data = _graph_payload(client)
    assert "Hidden Vendor" not in {n["label"] for n in data["nodes"]}
    assert not any(e["kind"] == "contracts_with" for e in data["edges"])
