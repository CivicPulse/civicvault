import datetime

import pytest
from django.db import IntegrityError

from catalog.models import (
    AgendaItem,
    Jurisdiction,
    Meeting,
    Motion,
    Organization,
    Person,
)


@pytest.fixture
def item(db):
    jur = Jurisdiction.objects.create(name="BCSD", slug="bcsd")
    body = Organization.objects.create(name="BOE", slug="boe", jurisdiction=jur)
    meeting = Meeting.objects.create(
        body=body, date=datetime.date(2025, 4, 17), kind=Meeting.Kind.COMMITTEE, slug="c"
    )
    return AgendaItem.objects.create(meeting=meeting, order=1, code="FSS-8", title="Chromebooks")


@pytest.mark.django_db
def test_motion_defaults_to_unreviewed_proposal(item):
    mover = Person.objects.create(full_name="Lisa Garrett-Boyd", slug="lisa-garrett-boyd")
    second = Person.objects.create(full_name="Myrtice Johnson", slug="myrtice-johnson")
    motion = Motion.objects.create(
        agenda_item=item,
        kind=Motion.Kind.INITIAL,
        sequence=0,
        moved_by=mover,
        seconded_by=second,
        result_text="Unanimously Approved",
        status=Motion.Status.UNANIMOUS,
    )
    assert motion.reviewed is False
    assert motion.moved_by == mover
    assert motion.seconded_by == second
    assert item.motions.count() == 1


@pytest.mark.django_db
def test_initial_and_amended_motions_coexist_on_one_item(item):
    Motion.objects.create(agenda_item=item, kind=Motion.Kind.INITIAL, sequence=0)
    Motion.objects.create(agenda_item=item, kind=Motion.Kind.AMENDED, sequence=1)
    assert item.motions.count() == 2


@pytest.mark.django_db
def test_motion_sequence_unique_per_item(item):
    Motion.objects.create(agenda_item=item, kind=Motion.Kind.SIMPLE, sequence=0)
    with pytest.raises(IntegrityError):
        Motion.objects.create(agenda_item=item, kind=Motion.Kind.AMENDED, sequence=0)


@pytest.mark.django_db
def test_motion_confidence_must_be_in_range(item):
    with pytest.raises(IntegrityError):
        Motion.objects.create(agenda_item=item, sequence=0, confidence=1.5)
