"""Shared data contract between P1 (detect/sanitize/formats) and P2 (linkage/privacy/release).

Agree on this file FIRST. Change it only when both people say yes.
Rule: no function in P1 or P2 may print or log any field of these objects (stdout is scanned for PII).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecordRef:
    """Points at exactly one record. Must match the locator written to records.jsonl."""
    file: str  # path relative to --input, posix style, e.g. "ward_a/admissions.csv"
    loc: str   # "row:N" (0-based, header excluded) | "/json/pointer" | "doc"


@dataclass(frozen=True)
class ParsedFile:
    """One decoded input file (formats.read_file)."""
    rel: str                      # path relative to --input, posix style
    kind: str                     # "table" | "json" | "text"
    text: str                     # decoded content
    delimiter: str = ","          # used when kind == "table"


@dataclass
class Clues:
    """P1 -> P2. Raw evidence found in ONE record. Values are as seen, not normalised
    (P2 normalises). Empty list / None means "not present", never a placeholder."""
    ref: RecordRef
    names: list[str] = field(default_factory=list)         # patient name variants, Latin or Devanagari
    relatives: list[str] = field(default_factory=list)     # S/o, D/o, W/o, C/O names. Weak evidence
    hospital_ids: list[str] = field(default_factory=list)  # MRN / UHID / admission no.
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    gov_ids: list[str] = field(default_factory=list)       # Aadhaar, PAN, ABHA
    dob: str | None = None                                 # ISO yyyy-mm-dd if parseable
    age: int | None = None
    sex: str | None = None                                 # "M" / "F" / "O" / None
    locations: list[str] = field(default_factory=list)     # village/mohalla/city/pincode, finest first


@dataclass
class Decision:
    """P2 -> P1. The privacy decision for ONE record.

    The sanitizer currently applies patient_id only. Ages in tables are banded with
    privacy.age_band() (width from policy.yaml). shift_days, age_band_years, location_level
    and suppress are produced here but NOT YET APPLIED to the output.
    """
    ref: RecordRef
    patient_id: str | None        # "PSN-XXXXXX" if linked; None if evidence too weak
    shift_days: int               # to be applied to EVERY date in the record (never 0)
    age_band_years: int           # width from policy.yaml
    location_level: str           # "keep" | "district" | "state" | "remove"
    suppress: bool = False        # True -> drop the record's quasi-identifiers (rare combo)


@dataclass
class SanitizeResult:
    """P1 -> P2 for one successfully cleaned file. Failures raise instead."""
    text: str                     # cleaned file content, same format as input
    records: list[dict]           # {"loc": ..., "patient": ...} per record, in file order
    identifiers_detected: int
    records_generalized: int = 0  # table rows and text notes; JSON/FHIR not counted yet
    new_name: str | None = None   # neutral file name if the original name held PII


# ---- call order used by main.py ----
# formats.read_file(rel: str, raw: bytes) -> ParsedFile                              (P1)
# detect.collect_clues(parsed: ParsedFile) -> list[Clues]                            (P1)
# linkage.link(all_clues: list[Clues]) -> dict[RecordRef, str | None]                (P2)
# privacy.decide(key: str | None, clues: Clues, book: PseudonymBook) -> Decision     (P2)
# sanitize.sanitize_file(parsed, decisions: dict[RecordRef, Decision]) -> SanitizeResult   (P1)
# release.safe_rel / choose_rel / write_sanitized / write_release(out, files, records, stats, seconds)   (P2)
