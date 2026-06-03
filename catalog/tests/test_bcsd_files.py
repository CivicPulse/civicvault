from pathlib import Path

from catalog.ingest.bcsd.files import document_kind_for, r2_key_for, title_for


def test_r2_key_locates_bcsd_component():
    p = Path("/anything/archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/mtg/files/hmh.pdf")
    assert r2_key_for(p) == "BCSD/BCSD_BOE_MEETINGS/2025/04/mtg/files/hmh.pdf"


def test_r2_key_works_for_tmp_test_layout():
    p = Path("/tmp/pytest-x/BCSD_BOE_MEETINGS/2025/04/mtg/files/a.pdf")
    assert r2_key_for(p) == "BCSD/BCSD_BOE_MEETINGS/2025/04/mtg/files/a.pdf"


def test_r2_key_without_bcsd_component_raises():
    import pytest

    with pytest.raises(ValueError):
        r2_key_for(Path("/tmp/no/collection/here/file.pdf"))


def test_document_kind_heuristics():
    assert document_kind_for("action-memo-math-adoption-signed.pdf") == "memo"
    assert document_kind_for("board-policy-garha-2nd-reading.pdf") == "policy"
    assert document_kind_for("regulation-afc-r-1-emergency-closings.pdf") == "policy"
    assert document_kind_for("school-consolidation-final.pptx") == "presentation"
    assert document_kind_for("fss-1m-1.PPT") == "presentation"
    assert document_kind_for("some-random-quote-52159.pdf") == "other"


def test_title_for_deslugs_filename():
    assert title_for("action-memo-math-adoption-signed.pdf") == "Action Memo Math Adoption Signed"
    assert title_for("hmh.pdf") == "Hmh"
