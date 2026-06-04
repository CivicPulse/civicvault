"""prune_orphans deletes edge-less proposal nodes (Persons / vendor Organizations)
with zero facts and zero relationships. Dry-run unless --apply. Bodies and connected
entities are never deleted."""

import datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command

from catalog.models import (
    AgendaItem,
    Appearance,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
    Relationship,
    Vote,
)


@pytest.fixture
def mixed(db):
    jur = Jurisdiction.objects.create(name="Bibb", slug="bibb")
    body = Organization.objects.create(
        name="BOE", slug="boe", jurisdiction=jur, kind=Organization.Kind.COMMITTEE
    )
    meeting = Meeting.objects.create(
        body=body, jurisdiction=jur, date=datetime.date(2025, 5, 15), slug="m1"
    )
    connected = Person.objects.create(full_name="Henry Ficklin", slug="henry")
    Appearance.objects.create(person=connected, meeting=meeting, role=Appearance.Role.MEMBER)
    orphan_person = Person.objects.create(full_name="They were:", slug="they-were")
    orphan_vendor = Organization.objects.create(
        name="Stale Vendor", slug="stale-vendor", jurisdiction=None, kind=Organization.Kind.COMPANY
    )
    return {
        "body": body,
        "meeting": meeting,
        "connected": connected,
        "orphan_person": orphan_person,
        "orphan_vendor": orphan_vendor,
    }


@pytest.mark.django_db
def test_dry_run_deletes_nothing(mixed):
    call_command("prune_orphans")  # no --apply
    assert Person.objects.filter(pk=mixed["orphan_person"].pk).exists()
    assert Organization.objects.filter(pk=mixed["orphan_vendor"].pk).exists()


@pytest.mark.django_db
def test_apply_deletes_only_orphans(mixed):
    call_command("prune_orphans", apply=True)
    assert not Person.objects.filter(pk=mixed["orphan_person"].pk).exists()
    assert not Organization.objects.filter(pk=mixed["orphan_vendor"].pk).exists()
    assert Person.objects.filter(pk=mixed["connected"].pk).exists()
    assert Organization.objects.filter(pk=mixed["body"].pk).exists()


@pytest.mark.django_db
def test_person_connected_only_by_vote_is_preserved(mixed):
    item = AgendaItem.objects.create(meeting=mixed["meeting"], order=1, title="Item")
    voter = Person.objects.create(full_name="Voter Only", slug="voter-only")
    Vote.objects.create(person=voter, agenda_item=item, value=Vote.Value.YEA)
    call_command("prune_orphans", apply=True)
    assert Person.objects.filter(pk=voter.pk).exists()


@pytest.mark.django_db
def test_person_referenced_as_relationship_object_is_preserved(mixed):
    person_ct = ContentType.objects.get_for_model(Person)
    org_ct = ContentType.objects.get_for_model(Organization)
    obj_person = Person.objects.create(full_name="Object Person", slug="object-person")
    Relationship.objects.create(
        subject_ct=org_ct,
        subject_id=mixed["body"].pk,
        object_ct=person_ct,
        object_id=obj_person.pk,
        predicate=Relationship.Predicate.BOARD_MEMBER_OF,
    )
    call_command("prune_orphans", apply=True)
    assert Person.objects.filter(pk=obj_person.pk).exists()
