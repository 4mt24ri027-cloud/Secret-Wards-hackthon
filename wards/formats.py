"""P1: readers and writers for CSV/TSV, JSON/FHIR and text files."""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Iterator
from pathlib import PurePosixPath

from .contracts import ParsedFile

_KINDS = {".csv": "table", ".tsv": "table", ".json": "json", ".txt": "text"}

def decode(raw: bytes) -> str | None:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None

def read_file(rel: str, raw: bytes) -> ParsedFile:
    """Decode one input file. The ValueError messages are quarantine codes, never file content."""
    ext = PurePosixPath(rel).suffix.lower()
    if ext not in _KINDS:
        raise ValueError("unsupported_format")
    if not raw.strip():
        raise ValueError("empty_file")
    text = decode(raw)
    if text is None:
        raise ValueError("undecodable_text")
    return ParsedFile(rel, _KINDS[ext], text, "\t" if ext == ".tsv" else ",")

# --------------------------------------------------------------------------- CSV / TSV
def read_rows(text: str, delimiter: str = ",") -> Iterator[list[str]]:
    """Read decoded text one row at a time, including the header."""
    with io.StringIO(text, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        yield from reader


def write_rows(rows: Iterable[list[str]], delimiter: str = ",") -> str:
    """Return CSV or TSV text with cell order and values preserved."""
    with io.StringIO(newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
        writer.writerows(rows)
        return stream.getvalue()

# --------------------------------------------------------------------------- JSON / FHIR
def load_json(text: str):
    return json.loads(text)


def dump_json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

def json_units(data):
    """Yield raw record locations, keeping component lists inside their owning record."""
    if isinstance(data, dict) and not (
        data.get("resourceType") or "patient" in data or "patient_ref" in data
    ):
        collections = [(k, v) for k, v in data.items()
                       if isinstance(v, list) and v and all(isinstance(item, dict) for item in v)]
        if collections:
            for field, items in collections:
                escaped = field.replace("~", "~0").replace("/", "~1")
                for i, item in enumerate(items):
                    yield f"/{escaped}/{i}", item
            return
    yield "doc", data
