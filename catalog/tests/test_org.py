import pytest
from django.db import IntegrityError

from catalog.models import Jurisdiction, Organization, Person, Source


@pytest.mark.django_db
def test_jurisdiction_and_source():
    jur = Jurisdiction.objects.create(
        name="Bibb County Board of Education",
        slug="bibb-county-boe",
        kind=Jurisdiction.Kind.SCHOOL_DISTRICT,
    )
    src = Source.objects.create(
        name="BCSD BOE Meetings",
        slug="bcsd-boe-meetings",
        jurisdiction=jur,
        adapter="bcsd",
    )
    assert str(jur) == "Bibb County Board of Education"
    assert str(src) == "bcsd-boe-meetings"
    assert src.jurisdiction == jur


@pytest.mark.django_db
def test_person_aka_and_slug():
    p = Person.objects.create(
        full_name="Myrtice Johnson",
        slug="myrtice-johnson",
        aka=["Ms. Myrtice Johnson"],
    )
    assert p.aka == ["Ms. Myrtice Johnson"]
    assert p.reviewed is False  # proposals default to unreviewed


@pytest.mark.django_db
def test_org_slug_unique_within_jurisdiction():
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    Organization.objects.create(
        name="Finance Committee", slug="finance-committee", jurisdiction=jur
    )
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="Finance Cmte", slug="finance-committee", jurisdiction=jur)


@pytest.mark.django_db
def test_global_vendor_slug_unique_when_no_jurisdiction():
    Organization.objects.create(name="CDW", slug="cdw", kind=Organization.Kind.COMPANY)
    with pytest.raises(IntegrityError):
        Organization.objects.create(name="CDW LLC", slug="cdw", kind=Organization.Kind.COMPANY)
