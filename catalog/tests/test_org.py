import pytest

from catalog.models import Jurisdiction, Source


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
