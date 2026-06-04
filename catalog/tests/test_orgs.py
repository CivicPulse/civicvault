"""Vendor-name canonicalization: deterministic collapse via key + curated alias map,
plus a conservative similarity pass that only *proposes* merges."""

from catalog.ingest.orgs import (
    canonicalize_org_name,
    org_key,
    propose_collapses,
    resolve_key,
)


def test_canonicalize_strips_legal_suffix():
    assert canonicalize_org_name("Amira Learning, Inc.") == "Amira Learning"
    assert canonicalize_org_name("School City LLC") == "School City"
    assert canonicalize_org_name("Infinite Campus Co.") == "Infinite Campus"


def test_canonicalize_strips_renewal_and_contract_tails():
    assert canonicalize_org_name("Imagine Learning - FY24 Renewal") == "Imagine Learning"
    assert canonicalize_org_name("Renaissance Star 360 - Contract") == "Renaissance Star 360"
    assert canonicalize_org_name("Amira Learning FY23 Renewal") == "Amira Learning"


def test_canonicalize_strips_leading_approval_or_renewal():
    assert canonicalize_org_name("Approval of Amira Learning") == "Amira Learning"
    assert canonicalize_org_name("Renewal of Imagine Learning") == "Imagine Learning"


def test_canonicalize_does_not_truncate_words_that_start_like_a_suffix():
    # "Co" is a suffix only as a standalone trailing token, never inside a word.
    assert canonicalize_org_name("Costar Technologies") == "Costar Technologies"
    assert canonicalize_org_name("Incite Group") == "Incite Group"


def test_org_key_unifies_surface_variants():
    assert org_key("Amira Learning, Inc.") == org_key("amira learning llc")
    assert org_key("Amira Learning") == "amira learning"


def test_resolve_key_applies_alias_map():
    # Curated alias collapses the School City variant onto the canonical key.
    assert resolve_key("School City Assessment Platform") == resolve_key("School City")
    assert resolve_key("School City") == "school city"


def test_propose_collapses_surfaces_unaliased_lookalike():
    pairs = propose_collapses(["Renaissance Star", "Renaissance Star 360", "Infinite Campus"])
    flat = {frozenset((a, b)) for a, b, _ in pairs}
    assert frozenset(("Renaissance Star", "Renaissance Star 360")) in flat
    assert frozenset(("Renaissance Star", "Infinite Campus")) not in flat


def test_propose_collapses_skips_pairs_already_unified_by_alias():
    # Already merged by the alias map -> never re-proposed.
    assert propose_collapses(["School City", "School City Assessment Platform"]) == []


def test_propose_collapses_skips_exact_key_matches():
    # Same canonical key (suffix-only difference) -> already one vendor -> not proposed.
    assert propose_collapses(["Amira Learning, Inc.", "Amira Learning LLC"]) == []
