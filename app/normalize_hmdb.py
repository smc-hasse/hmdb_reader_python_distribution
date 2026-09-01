import re


HMDB_PATTERN = re.compile(r"^HMDB(\d+)$", re.IGNORECASE)


def normalize_hmdb(value: str) -> str:
    """Normalize a single HMDB accession to a canonical 7-digit value."""
    match = HMDB_PATTERN.fullmatch((value or "").strip())
    if match is None:
        return ""

    digits = match.group(1)
    if len(digits) > 7:
        return ""
    return f"HMDB{digits.zfill(7)}"
