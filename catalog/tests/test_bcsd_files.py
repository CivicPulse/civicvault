from pathlib import Path

import pytest

from catalog.ingest.bcsd.files import (
    _pg_safe_text,
    document_kind_for,
    extract_pdf_text,
    r2_key_for,
    title_for,
)
from catalog.tests.fixtures.pdfs import write_empty_pdf, write_text_pdf


def test_pg_safe_text_strips_nul_and_surrogates():
    """PDF text layers can carry bytes PostgreSQL rejects; sanitize, keep the rest."""
    dirty = "Budget\x00 line \udb40item — $5,000"
    clean = _pg_safe_text(dirty)
    assert "\x00" not in clean
    # the cleaned text must round-trip to UTF-8 (PostgreSQL stores UTF-8)
    clean.encode("utf-8")
    assert clean.startswith("Budget")
    assert "$5,000" in clean and "—" in clean


def test_pg_safe_text_leaves_clean_text_untouched():
    s = "Ordinary minutes text with $1,234.56 and café."
    assert _pg_safe_text(s) == s


def test_r2_key_locates_bcsd_component():
    p = Path("/anything/archive_data/bcsd/BCSD_BOE_MEETINGS/2025/04/mtg/files/hmh.pdf")
    assert r2_key_for(p) == "BCSD/BCSD_BOE_MEETINGS/2025/04/mtg/files/hmh.pdf"


def test_r2_key_works_for_tmp_test_layout():
    p = Path("/tmp/pytest-x/BCSD_BOE_MEETINGS/2025/04/mtg/files/a.pdf")
    assert r2_key_for(p) == "BCSD/BCSD_BOE_MEETINGS/2025/04/mtg/files/a.pdf"


def test_r2_key_without_bcsd_component_raises():
    with pytest.raises(ValueError):
        r2_key_for(Path("/tmp/no/collection/here/file.pdf"))


def test_document_kind_heuristics():
    assert document_kind_for("action-memo-math-adoption-signed.pdf") == "memo"
    assert document_kind_for("board-policy-garha-2nd-reading.pdf") == "policy"
    assert document_kind_for("regulation-afc-r-1-emergency-closings.pdf") == "policy"
    assert document_kind_for("school-consolidation-final.pptx") == "presentation"
    assert document_kind_for("fss-1m-1.PPT") == "presentation"
    assert document_kind_for("some-random-quote-52159.pdf") == "other"
    assert document_kind_for("feb-12-minutes.pdf") == "minutes"
    assert document_kind_for("hcca-school-council-meeting-agenda-december-13-2021.pdf") == "agenda"


def test_title_for_deslugs_filename():
    assert title_for("action-memo-math-adoption-signed.pdf") == "Action Memo Math Adoption Signed"
    assert title_for("hmh.pdf") == "Hmh"
    assert title_for("HMH_Math_2025.pdf") == "Hmh Math 2025"


def test_extract_pdf_text_has_text(tmp_path):
    pdf = write_text_pdf(tmp_path / "t.pdf")
    text, status = extract_pdf_text(pdf)
    assert "chromebooks" in text
    assert status == "has_text"


def test_extract_pdf_text_no_text_layer_is_ocr_needed(tmp_path):
    pdf = write_empty_pdf(tmp_path / "e.pdf")
    text, status = extract_pdf_text(pdf)
    assert text == ""
    assert status == "ocr_needed"


def test_extract_pdf_text_unreadable_is_unknown(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not really a pdf")
    text, status = extract_pdf_text(bad)
    assert text == ""
    assert status == "unknown"
