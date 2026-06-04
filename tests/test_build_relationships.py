"""Tests for the build_relationships derivation command.

It must produce only citation-backed relationships from real corpus signals:
board members from member appearances, and vendor contracts (with amounts) from
clean renewal/contract agenda titles. It must be idempotent.
"""

import datetime
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from catalog.models import (
    AgendaItem,
    Appearance,
    Citation,
    Document,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Relationship,
)


@pytest.fixture
def corpus(db):
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE, reviewed=True
    )
    meeting = Meeting.objects.create(
        body=body, jurisdiction=jur, date=datetime.date(2025, 5, 15), slug="m1"
    )
    Document.objects.create(title="Minutes", meeting=meeting, kind=Document.Kind.MINUTES)
    person = Person.objects.create(full_name="Henry Ficklin", slug="henry", reviewed=True)
    Appearance.objects.create(
        person=person, meeting=meeting, role=Appearance.Role.MEMBER, reviewed=True
    )
    AgendaItem.objects.create(
        meeting=meeting,
        order=1,
        title="Renewal of Amira Learning",
        outcome_text="Approved in an amount not to exceed $255,300.00.",
        amount=Decimal("255300.00"),
        amount_text="in an amount not to exceed $255,300.00",
    )
    # a process item that must NOT become a vendor
    AgendaItem.objects.create(meeting=meeting, order=2, title="Approval of Food Bid")
    return {"body": body, "person": person, "meeting": meeting}


@pytest.mark.django_db
def test_derives_board_member_with_citation(corpus):
    call_command("build_relationships", review=True)
    rel_ct = ContentType.objects.get_for_model(Relationship)
    bm = Relationship.objects.filter(predicate=Relationship.Predicate.BOARD_MEMBER_OF)
    assert bm.count() == 1
    rel = bm.first()
    assert rel.subject_id == corpus["person"].pk
    assert rel.object_id == corpus["body"].pk
    assert rel.reviewed is True
    assert Citation.objects.filter(content_type=rel_ct, object_id=rel.pk).exists()


@pytest.mark.django_db
def test_derives_vendor_contract_with_amount_and_citation(corpus):
    call_command("build_relationships", review=True)
    vendor = Organization.objects.filter(kind=Organization.Kind.COMPANY).first()
    assert vendor is not None and vendor.name == "Amira Learning"
    rel = Relationship.objects.get(predicate=Relationship.Predicate.CONTRACTS_WITH)
    assert rel.subject_id == corpus["body"].pk
    assert rel.object_id == vendor.pk
    assert str(rel.amount) == "255300.00"
    rel_ct = ContentType.objects.get_for_model(Relationship)
    assert Citation.objects.filter(content_type=rel_ct, object_id=rel.pk).exists()


@pytest.mark.django_db
def test_process_items_do_not_become_vendors(corpus):
    call_command("build_relationships", review=True)
    names = set(Organization.objects.values_list("name", flat=True))
    assert "Food Bid" not in names
    assert not any("Bid" in n for n in names if n != "BOE")


@pytest.mark.django_db
def test_rebuild_is_idempotent(corpus):
    call_command("build_relationships", review=True)
    first = Relationship.objects.count()
    rel_ct = ContentType.objects.get_for_model(Relationship)
    cites_first = Citation.objects.filter(content_type=rel_ct).count()
    call_command("build_relationships", review=True)
    assert Relationship.objects.count() == first
    assert Citation.objects.filter(content_type=rel_ct).count() == cites_first


@pytest.mark.django_db
def test_default_is_unreviewed_proposals(corpus):
    call_command("build_relationships")  # no --review
    assert Relationship.objects.exclude(reviewed=False).count() == 0


@pytest.mark.django_db
def test_amount_comes_from_structured_field_not_text(corpus):
    # An item whose text contains a larger *governance threshold* figure but whose
    # structured amount is the real contract value must use the structured value.
    item = AgendaItem.objects.get(title="Renewal of Amira Learning")
    item.outcome_text = "Contract in excess of $999,999.00 prohibited. Approved."
    item.save(update_fields=["outcome_text"])
    call_command("build_relationships", review=True)
    rel = Relationship.objects.get(predicate=Relationship.Predicate.CONTRACTS_WITH)
    assert str(rel.amount) == "255300.00"  # from item.amount, not the $999,999 in text
