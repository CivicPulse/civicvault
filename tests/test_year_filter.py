"""Tests for the year filter on the graph and search.

Two surfaces, two mechanisms:

- **Graph** filters client-side, so the server's job is to *emit the contract* the
  JS cascade runs on: every dated edge carries the `years` it happened in, each
  row carries its `year` (and contracts a raw `amt`), and the no-JS list exposes
  the same `data-years` + endpoint ids. These tests pin that contract.
- **Search** filters server-side, so a `?year=` actually narrows the querysets.
  These tests exercise the real behaviour end to end.
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

GRAPH_DATA_RE = re.compile(r'id="graph-data" type="application/json">(.*?)</script>', re.S)


def _graph_payload(client):
    resp = client.get("/graph/")
    assert resp.status_code == 200
    match = GRAPH_DATA_RE.search(resp.content.decode())
    assert match, "graph-data json_script block missing from response"
    return resp, json.loads(match.group(1))


def _make_relationship(subject, obj, predicate, **kwargs):
    return Relationship.objects.create(
        subject_ct=ContentType.objects.get_for_model(subject),
        subject_id=subject.pk,
        object_ct=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
        predicate=predicate,
        **kwargs,
    )


@pytest.fixture
def multiyear(db):
    """A body whose record spans two years: one person active only in 2023, one
    active only in 2025 — the shape behind the 'filter Jwan Jackson out' case."""
    jur = Jurisdiction.objects.create(
        name="Bibb County BOE", slug="bibb", kind=Jurisdiction.Kind.SCHOOL_DISTRICT
    )
    body = Organization.objects.create(
        name="Board of Education", slug="boe", jurisdiction=jur, reviewed=True
    )
    m2023 = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2023, 5, 1),
        kind=Meeting.Kind.BOARD,
        slug="m2023",
    )
    m2025 = Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 5, 1),
        kind=Meeting.Kind.BOARD,
        slug="m2025",
    )
    # A second 2025 meeting: years must still de-duplicate to one 2025 entry
    # (guards the DISTINCT-vs-default-ordering trap in _corpus_years).
    Meeting.objects.create(
        body=body,
        jurisdiction=jur,
        date=datetime.date(2025, 9, 1),
        kind=Meeting.Kind.COMMITTEE,
        slug="m2025b",
    )
    item = AgendaItem.objects.create(meeting=m2025, order=1, title="Budget")

    departed = Person.objects.create(full_name="Jwan Jackson", slug="jwan", reviewed=True)
    current = Person.objects.create(full_name="Henry Ficklin", slug="henry", reviewed=True)
    Appearance.objects.create(
        person=departed, meeting=m2023, reviewed=True, role=Appearance.Role.MEMBER
    )
    Appearance.objects.create(
        person=current, meeting=m2025, reviewed=True, role=Appearance.Role.MEMBER
    )
    Vote.objects.create(person=current, agenda_item=item, value=Vote.Value.YEA, reviewed=True)

    Document.objects.create(
        title="Budget Packet",
        text="annual budget summary",
        meeting=m2025,
        access_level=Document.AccessLevel.PUBLIC,
        source_url="https://example.org/b.pdf",
    )
    Document.objects.create(
        title="Old Budget",
        text="annual budget summary",
        meeting=m2023,
        access_level=Document.AccessLevel.PUBLIC,
        source_url="https://example.org/o.pdf",
    )
    return {"jur": jur, "body": body, "departed": departed, "current": current}


# --------------------------------------------------------------- graph contract


@pytest.mark.django_db
def test_corpus_years_listed_newest_first(client, multiyear):
    resp = client.get("/graph/")
    body = resp.content.decode()
    assert "data-graph-years" in body
    # the control offers each corpus year, newest first
    assert resp.context["years"] == [2025, 2023]
    assert 'data-year="2025"' in body and 'data-year="2023"' in body


@pytest.mark.django_db
def test_person_edges_carry_their_years(client, multiyear):
    _resp, data = _graph_payload(client)
    by_target = {}
    for e in data["edges"]:
        if e["source"].startswith("person-"):
            by_target[e["source"]] = e
    departed = by_target[f"person-{multiyear['departed'].pk}"]
    current = by_target[f"person-{multiyear['current'].pk}"]
    assert departed["years"] == [2023]
    assert current["years"] == [2025]
    # every meeting row carries the year the JS cascade scopes on
    assert all("year" in r for r in current["rows"])


@pytest.mark.django_db
def test_structural_edge_has_no_years(client, multiyear):
    """The body -> jurisdiction 'sits in' tie is scaffolding: no year of its own."""
    _resp, data = _graph_payload(client)
    sits_in = next(e for e in data["edges"] if e["kind"] == "in")
    assert sits_in.get("years", []) == []


@pytest.mark.django_db
def test_contract_rows_carry_year_and_raw_amount(client, multiyear):
    vendor = Organization.objects.create(
        name="Acme Copiers", slug="acme", kind=Organization.Kind.COMPANY, reviewed=True
    )
    _make_relationship(
        multiyear["body"],
        vendor,
        Relationship.Predicate.CONTRACTS_WITH,
        amount=Decimal("125000.00"),
        occurred_on=datetime.date(2025, 3, 1),
        note="Copier lease",
        reviewed=True,
    )
    _resp, data = _graph_payload(client)
    edge = next(e for e in data["edges"] if e["kind"] == "contracts_with")
    assert edge["years"] == [2025]
    row = edge["rows"][0]
    assert row["year"] == 2025
    assert row["amt"] == 125000.0  # raw number lets the client re-sum per year


@pytest.mark.django_db
def test_list_edges_expose_years_and_endpoint_ids(client, multiyear):
    """The no-JS list mirrors the graph filter: each edge ships its years and both
    endpoint ids, so structural ties can ride their endpoints' visibility."""
    body = client.get("/graph/").content.decode()
    assert 'data-years="2025"' in body
    assert "data-source-id=" in body and "data-target-id=" in body


# ------------------------------------------------------------- search filtering


@pytest.mark.django_db
def test_search_without_year_spans_all_years(client, multiyear):
    resp = client.get("/search/", {"q": "budget"})
    assert resp.context["doc_total"] == 2
    assert resp.context["selected_year"] is None


@pytest.mark.django_db
def test_search_year_narrows_to_that_year(client, multiyear):
    resp = client.get("/search/", {"q": "budget", "year": "2025"})
    assert resp.context["selected_year"] == 2025
    assert resp.context["doc_total"] == 1
    titles = {d["title"] for d in resp.context["doc_hits"]}
    assert titles == {"Budget Packet"}


@pytest.mark.django_db
def test_search_offered_year_with_no_hits_is_empty_not_unfiltered(client, multiyear):
    """An offered year that the query doesn't match returns zero — never a silent
    fall back to all years. 'packet' only appears in the 2025 doc's title."""
    assert client.get("/search/", {"q": "packet"}).context["doc_total"] == 1
    resp = client.get("/search/", {"q": "packet", "year": "2023"})
    assert resp.context["selected_year"] == 2023
    assert resp.context["doc_total"] == 0


@pytest.mark.django_db
def test_search_ignores_unknown_year(client, multiyear):
    """A junk or non-offered ?year= falls back to 'All', never a 500. 2024 isn't a
    corpus year here, so it is treated exactly like nonsense."""
    for bad in ("nonsense", "2024"):
        resp = client.get("/search/", {"q": "budget", "year": bad})
        assert resp.status_code == 200
        assert resp.context["selected_year"] is None
        assert resp.context["doc_total"] == 2
