"""P1: field classification, text span patterns and per-record patient clues."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .contracts import Clues, ParsedFile, RecordRef
from .formats import json_units, load_json, read_rows

# --------------------------------------------------------------------------- column / key names

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

def classify_columns(headers: list[str]) -> list[str | None]:
    """Interpret ambiguous name columns only in patient-registration tables."""
    types = [classify_header(header) for header in headers]
    keys = [_normalize(header) for header in headers]
    has_patient_id = "MRN" in types or bool({"patientid", "regno"}.intersection(keys))
    has_birth_date = any(key.startswith("dob") or key in {"dateofbirth", "janmtithi"} for key in keys)
    if has_patient_id and has_birth_date:
        for i, key in enumerate(keys):
            if key in {"naam", "firstname", "lastname"}:
                types[i] = "PATIENT_NAME"
    return types

# --------------------------------------------------------------------------- text span patterns
#   * column-aware rules: a column named like a name/phone/address is PII whatever it contains
#     (but expect renamed columns on hidden data: "Patient's Name", "Gram/Mohalla", ...);
#   * a name gazetteer in Latin AND Devanagari, transliteration (Mohammad/Mohd/Md./मोहम्मद),
#     honorifics (ji, sahab, didi, श्री), relatives (S/o, D/o, W/o, C/O <name>);
#   * the meaning traps: "C/O fever" is a complaint, "Dr. Ramesh" stays, "Dolo 650", "5 mg",
#     "1-0-1" are doses, "Parkinson's disease" is not a person;
#   * JSON keys, CSV headers, file names and base64 attachments can all hold PII.
PERSON_WORD = r"[A-Z][^\W\d_]*(?:[-'’][^\W\d_]+)*"
PERSON_NAME = rf"{PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{1,3}}"
# Kinship labels identify a relative even when only a first name is given.
RELATIVE_WORD = rf"(?:{PERSON_WORD}|[ऄ-हक़-ॡ][ऀ-ःऄ-ह़-ॣ]*)"
RELATIVE_LABEL = re.compile(
    rf"(?P<label>(?<![\w/])(?i:[swd]/o|attendant:|पिता का नाम:|पति का नाम:|माता का नाम:)[ \t]+)"
    rf"{RELATIVE_WORD}(?:[ \t]+{RELATIVE_WORD}){{0,3}}"
)
PATTERNS = [
    ("PATIENT_NAME", re.compile(
        rf"\b{PERSON_WORD}(?=[ \t]+(?i:bhai|amma|ji|didi|sahab|behenji|bhenji|babu)"
        r"[ \t]+ki[ \t]+condition\b)"
    )),
    ("PATIENT_NAME", re.compile(
        rf"(?m)^{PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{0,2}}(?=,[ \t]*(?i:[swd]/o)\s)"
    )),
    ("PATIENT_NAME", re.compile(
        rf"(?<=(?i:sample received from) ){RELATIVE_WORD}(?:[ \t]+{RELATIVE_WORD}){{0,3}}"
        r"(?=['’]s[ \t]+(?i:attendant)\b)"
    )),
    # Hospital record numbers in narrative text, including year/serial forms.
    ("MRN", re.compile(
        r"(?i)(?<![\w/-])(?:UHID|MRN|IPD|IP|ADM|JJH|SNJ|DHH)"
        r"(?:[-/](?:IPD|\d{2,4}))?[-/]?\d{5,9}(?![\w/-])"
    )),
    ("CONTACT_NAME", re.compile(rf"(?<=(?i:called by) ){PERSON_NAME}(?=[ \t]+[+\d])")),
    ("WITNESS_NAME", re.compile(rf"(?<=(?i:witnessed by) ){PERSON_NAME}(?=[,.;]|$)")),
    ("VISITOR_NAME", re.compile(rf"{PERSON_NAME}(?=[ \t]*\((?i:attendant|visitor)\b)")),
    # A name at the start of a Hinglish note, followed by an honorific and BP reading.
    ("PATIENT_NAME", re.compile(
        r"(?m)^[A-Z][a-z]+(?:[ -][A-Z][a-z]+){0,2}"
        r"(?=[ \t]+(?i:behenji|bhenji|amma|bhai|babu|didi|ji|sahab)[ \t]+(?i:ka bp)[ \t]+\d{2,3}/\d{2,3}\b)"
    )),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)")),
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("NAME", re.compile(r"(?i)(?<=name:)\s*[^\n,;|]+")),
]

MRN_PATTERN = next(rx for kind, rx in PATTERNS if kind == "MRN")

NOTE_ADDRESS = re.compile(r"(?im)^([ \t]*(?:address|पता|village|ग्राम|गाँव)[ \t]*:[ \t]*)[^\r\n]+")
NOTE_DOB = re.compile(
    r"(?im)^([ \t]*(?:DOB|date of birth|जन्म तिथि)[ \t]*:[ \t]*)"
    r"\d{1,4}[-/.]\d{1,2}[-/.]\d{2,4}\b"
)

HINDI_NAME_LINE = re.compile(
    r"(?m)^[ \t]*(?:रोगी का नाम|मरी(?:ज़|ज़|ज) का नाम|नाम)[ \t]*:[ \t]*"
    r"(?P<name>[ऄ-हक़-ॡ][ऀ-ःऄ-ह़-ॣ]*(?:[ \t]+[ऄ-हक़-ॡ][ऀ-ःऄ-ह़-ॣ]*){0,5}?)"
    r"(?=[ \t]*(?:आयु[ \t]*:|उम्र[ \t]*:|[,;|\r\n]|$))"
)

VISIT_BP_SUBJECT = re.compile(
    rf"^{PERSON_WORD}(?=[ \t]+ka[ \t]+BP[ \t]+\d{{2,3}}/\d{{2,3}}\b)"
)
GENERIC_BP_SUBJECTS = {"patient", "pt", "mareez", "mariz", "mother", "father",
                       "baby", "child", "doctor", "nurse", "ward", "aaj", "kal"}

# --------------------------------------------------------------------------- patient clues
def extract_clues(ref, fields, narrative=""):
    clues = Clues(ref)
    targets = {"PATIENT_NAME": clues.names, "MRN": clues.hospital_ids, "PHONE": clues.phones,
               "RELATIVE_NAME": clues.relatives, "AADHAAR": clues.gov_ids, "ABHA_NUMBER": clues.gov_ids}
    for key, value in fields:
        if not isinstance(value, (str, int)) or not str(value).strip():
            continue
        raw = str(value).strip()
        kind = classify_header(key)
        if key.casefold() in {"patient_ref", "hospital_uhid"}:
            kind = "MRN"
        if kind in targets:
            if kind == "MRN" and raw.isdigit():
                # A bare local serial lacks a cross-hospital namespace.
                raw = ref.file + "|" + raw
            targets[kind].append(raw)
        if key.casefold() in {"gender", "sex"}:
            clues.sex = raw
    ids = set(MRN_PATTERN.findall(narrative))
    if len(ids) == 1:
        clues.hospital_ids.extend(ids)
    return clues

def json_fields(unit):
    if not isinstance(unit, dict):
        return []
    if unit.get("resourceType") == "Bundle":
        entries = unit.get("entry")
        if not isinstance(entries, list):
            return []
        patients = [entry.get("resource") for entry in entries if isinstance(entry, dict)]
        patients = [p for p in patients if isinstance(p, dict) and p.get("resourceType") == "Patient"]
        if len(patients) != 1:
            return []
        fields = []
        identifiers = patients[0].get("identifier")
        if not isinstance(identifiers, list):
            return []
        for identifier in identifiers:
            if isinstance(identifier, dict) and MRN_PATTERN.fullmatch(str(identifier.get("value", ""))):
                fields.append(("MRN", identifier["value"]))
        return fields
    fields = list(unit.items())
    patient = unit.get("patient", unit)
    if isinstance(patient, dict):
        fields.extend(patient.items() if patient is not unit else [])
        name = patient.get("name")
        if isinstance(name, dict):
            name = " ".join(str(name.get(k) or "") for k in ("first", "last")).strip()
        fields.append(("Patient Name", name))
        for key in ("contact", "ids"):
            if isinstance(patient.get(key), dict):
                fields.extend(patient[key].items())
    return fields

def collect_clues(parsed: ParsedFile) -> list[Clues]:
    """One Clues object per record, with the same locators the sanitizer writes."""
    rel = parsed.rel
    if parsed.kind == "table":
        rows = read_rows(parsed.text, parsed.delimiter)
        header = next(rows, [])
        return [extract_clues(RecordRef(rel, f"row:{i}"), zip(header, row)) for i, row in enumerate(rows)]
    if parsed.kind == "json":
        return [extract_clues(RecordRef(rel, loc), json_fields(unit))
                for loc, unit in json_units(load_json(parsed.text))]
    return [extract_clues(RecordRef(rel, "doc"), [], parsed.text)]
