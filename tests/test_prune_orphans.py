"""prune_orphans deletes edge-less proposal nodes (Persons / vendor Organizations)
with zero facts and zero relationships. Dry-run unless --apply. Bodies and connected
entities are never deleted."""

import datetime

import pytest
from django.core.management import call_command

from catalog.models import (
    Appearance,
    Jurisdiction,
    Meeting,
    Organization,
    Person,
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
