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
    """P2 -> P1. What P1's sanitizer must apply to ONE record."""
    ref: RecordRef
    patient_id: str | None        # "PSN-XXXXXX" if linked; None if evidence too weak
    shift_days: int               # applied to EVERY date in the record (never 0)
    age_band_years: int           # width from policy.yaml; P1 calls privacy.age_band()
    location_level: str           # "keep" | "district" | "state" | "remove"
    suppress: bool = False        # True -> drop the record's quasi-identifiers (rare combo)


@dataclass
class SanitizeResult:
    """P1 -> P2 for one file."""
    text: str                     # cleaned file content (UTF-8), same format as input
    identifiers_detected: int
    new_name: str | None = None   # cleaned file name if the original name held PII
    ok: bool = True               # False -> release.py quarantines the file
    reason: str = ""              # short identifier like "bad_json"; never file content


# ---- function signatures each side promises (implement in the named module) ----
# formats.py   read_file(path: Path) -> ParsedFile                      (P1)
# detect.py    collect_clues(parsed: ParsedFile) -> list[Clues]         (P1)
# linkage.py   link(all_clues: list[Clues]) -> dict[RecordRef, str|None]  canonical key per record  (P2)
# privacy.py   decide(key: str|None, clues: Clues) -> Decision          (P2)
# sanitize.py  sanitize_file(parsed: ParsedFile, decisions: dict[RecordRef, Decision]) -> SanitizeResult  (P1)
# release.py   write_release(results, decisions, out_dir) -> None       (P2)