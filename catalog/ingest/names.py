"""Person-name normalization (brief §5.2).

Strips a leading honorific, collapses internal whitespace, and trims a trailing
", <Role>". OCR typos and unknown prefixes (e.g. "Attorney") are preserved
verbatim — resolution against the roster and cross-meeting dedup happen later.
"""

import re

_HONORIFIC = re.compile(r"^(Ms|Mr|Mrs|Dr|Miss)\.?\s+", re.IGNORECASE)
_WS = re.compile(r"\s+")


def normalize_name(raw: str) -> str:
    """Return a clean display name: no honorific, single-spaced, no trailing role."""
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
    text = _HONORIFIC.sub("", text).strip()
    return text, role
