"""Person-name normalization (brief §5.2).

Strips leading honorifics and professional titles, collapses internal whitespace,
and trims a trailing ", <Role>". The title list is grounded in the real BCSD
archive (Attorney, Superintendent, President, Reverend/Rev, Pastor, Mayor, Judge,
Officer, Coach, Chair*, Council*), each optionally preceded by a Vice/Assistant/
Deputy/Associate/Interim modifier. OCR typos and genuinely unknown words are
preserved verbatim; the raw source string is always retained on ParsedPerson
(raw_name) for provenance/audit, so stripping the display name is non-destructive.

A prefix is only stripped when followed by a separator (period/space), so ordinary
names that merely *start* with a title's letters — "Drew Carey", "Presley Adams" —
are left untouched.
"""

import re

_HONORIFIC = re.compile(r"^(?:Ms|Mr|Mrs|Dr|Miss)\.?\s+", re.IGNORECASE)
_TITLE = re.compile(
    r"^(?:(?:Vice|Assistant|Asst|Deputy|Associate|Interim)\.?[\s-]+)?"
    r"(?:Attorney|Superintendent|President|Chair(?:man|woman|person)?|"
    r"Reverend|Rev|Pastor|Mayor|Judge|Officer|Coach|"
    r"Councilman|Councilwoman|Councilmember|Commissioner)"
    r"\.?\s+",
    re.IGNORECASE,
)
_WS = re.compile(r"\s+")

_NAME_TOKEN = re.compile(r"^[A-Z][A-Za-z'\u2018\u2019.\-]*$")
_NAME_PARTICLES = {"de", "van", "von", "der", "da", "del", "la", "di", "bin", "al"}


def looks_like_name(text: str) -> bool:
    """True if text is shaped like a person name: 1–5 tokens, no terminal sentence
    punctuation, every token Capitalized (or a known nobiliary particle). Rejects
    prose ("Four people addressed the Board.") and role descriptors ("Board member").

    Expects already-normalized text (callers pass normalize_name(raw)); it does not
    itself strip honorifics, so "Dr. Henry Ficklin" would pass as-is."""
    text = (text or "").strip()
    if not text or text[-1] in ".:;,":
        return False
    toks = text.split()
    if not (1 <= len(toks) <= 5):
        return False
    return all(t.lower() in _NAME_PARTICLES or bool(_NAME_TOKEN.match(t)) for t in toks)


def normalize_name(raw: str) -> str:
    """Return a clean display name: no honorific/title, single-spaced, no trailing role."""
    name, _role = split_name_and_role(raw)
    return name


def split_name_and_role(raw: str) -> tuple[str, str]:
    """Return (clean_name, role). Role is the text after the first comma, or ""."""
    text = _WS.sub(" ", raw).strip()
    role = ""
    if "," in text:
        text, _, role = text.partition(",")
        text = text.strip()
        role = role.strip()
    # Strip stacked leading prefixes in any order ("Rev. Dr. John" -> "John").
    prev = None
    while prev != text:
        prev = text
        text = _HONORIFIC.sub("", text).strip()
        text = _TITLE.sub("", text).strip()
    return text, role
