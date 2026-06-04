"""Organization-name canonicalization (brief §7, §14.4); mirrors names.py for people.

Pure and Django-free, so it is unit-testable and reusable by both the loader (body
orgs) and build_relationships (vendor orgs). Deterministic collapses — a normalized
key match, or a curated alias — are applied at create time and recorded in
Organization.aka. Fuzzy look-alikes are only *proposed* by propose_collapses(); a
human promotes accepted pairs into VENDOR_ALIASES, the auditable merge ledger. This
is the seed of the Phase 4 Splink-based resolution.
"""

import re

_LEADING = re.compile(r"^(?:approval\s+of|renewal\s+of)\s+", re.IGNORECASE)
_TRAILING = re.compile(
    r"\s*[-–]\s*(?:contract|fy\s*\d*\s*renewal)\s*$|\s*fy\s*\d*\s*renewal\s*$",
    re.IGNORECASE,
)
_SUFFIX = re.compile(
    r"[,\s]+(?:inc|incorporated|llc|l\.l\.c\.|co|corp|corporation|ltd|company)\.?$",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9\s]")

# Generic words ignored when comparing token sets, so "School City" ⊂ "School City
# Assessment Platform" stays detectable while filler words don't inflate overlap.
_STOP = {"the", "of", "and", "for", "a", "an", "services", "service", "system", "systems"}


def canonicalize_org_name(raw: str) -> str:
    """Clean display name: strip Approval/Renewal lead-ins, FY/contract tails, and a
    single trailing legal suffix; collapse whitespace. Empty result falls back to raw."""
    name = _WS.sub(" ", (raw or "")).strip()
    name = _LEADING.sub("", name).strip()
    prev = None
    while prev != name:
        prev = name
        name = _TRAILING.sub("", name).strip(" .,-–")
    name = _SUFFIX.sub("", name).strip(" .,-–")
    return name or _WS.sub(" ", (raw or "")).strip()


def org_key(raw: str) -> str:
    """Lowercased, punctuation-stripped matching key for the canonical name."""
    name = _PUNCT.sub(" ", canonicalize_org_name(raw).lower())
    return _WS.sub(" ", name).strip()


# Curated merge ledger: variant key -> canonical key. Promote accepted
# propose_collapses() suggestions here; the next build collapses them deterministically.
VENDOR_ALIASES: dict[str, str] = {
    "school city assessment platform": "school city",
}


def resolve_key(raw: str) -> str:
    """org_key() then a single alias redirect to the canonical key."""
    key = org_key(raw)
    return VENDOR_ALIASES.get(key, key)


def _tokens(key: str) -> set[str]:
    return {t for t in key.split() if t not in _STOP}


def propose_collapses(names, threshold: float = 0.6) -> list[tuple[str, str, float]]:
    """Suggest (name_a, name_b, score) pairs that look like the same vendor but are NOT
    yet unified by key or alias. Pure-Python token-set Jaccard + subset containment.

    Suggestions only — this mutates nothing and is the input to a human decision. It
    cannot distinguish a true variant from two distinct entities (that is why a human
    confirms); the guarantee is the reverse: an already-unified pair is never proposed.
    """
    resolved = [(n, resolve_key(n)) for n in names]
    proposals: list[tuple[str, str, float]] = []
    for i in range(len(resolved)):
        for j in range(i + 1, len(resolved)):
            (na, ka), (nb, kb) = resolved[i], resolved[j]
            if ka == kb:
                continue  # already the same vendor (key or alias) — never re-propose
            ta, tb = _tokens(ka), _tokens(kb)
            if not ta or not tb:
                continue
            subset = ta <= tb or tb <= ta
            jaccard = len(ta & tb) / len(ta | tb)
            if subset or jaccard >= threshold:
                proposals.append((na, nb, round(1.0 if subset else jaccard, 3)))
    return proposals
