"""Recognize personal-data columns in structured hospital records."""

import json
import unicodedata
from pathlib import Path


def _normalize(header: str) -> str:
    text = unicodedata.normalize("NFKC", header).casefold()
    return "".join(c for c in text if unicodedata.category(c)[0] in "LNM")


_alias_file = Path(__file__).resolve().parents[1] / "config" / "field_aliases.json"
with _alias_file.open(encoding="utf-8-sig") as stream:
    _field_types = {
        _normalize(alias): field_type
        for field_type, aliases in json.load(stream).items()
        for alias in aliases
    }


def classify_header(header: str) -> str | None:
    """Return a known field type, or None if the header needs other checks."""
    return _field_types.get(_normalize(header))
