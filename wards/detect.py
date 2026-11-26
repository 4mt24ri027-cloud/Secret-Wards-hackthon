"""P1: field classification, text span patterns and per-record patient clues."""
from __future__ import annotations
from .dates import detect_order, parse_date

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
# Words that can precede an honorific without being a person's name.
_NOT_BEFORE_HONORIFIC = (r"(?!(?:Dr|Doctor|Sir|Madam|Sister|Nurse|Haan|Nahi|Patient|Mareez|Mata|Pita"
                         r"|Ward|Bed|Aap|Ok|Okay|Ji)\b)")
_NOT_DOCTOR = r"(?<!Dr )(?<!Dr\. )"

PATTERNS = [
    # "Kamal Bhaiya", "Mohan Papa": a name followed by a kinship word is a relative.
    ("RELATIVE_NAME", re.compile(
        rf"\b{_NOT_DOCTOR}{_NOT_BEFORE_HONORIFIC}{PERSON_WORD}"
        r"(?=[ \t]+(?i:bhaiya|chachu|chacha|mama|mausi|papa|mummy)\b)"
    )),
    # "Asha ji", "Shahid sahab": a name followed by an honorific is the person spoken about.
    ("PATIENT_NAME", re.compile(
        rf"\b{_NOT_DOCTOR}{_NOT_BEFORE_HONORIFIC}{PERSON_WORD}"
        rf"(?:[ \t]+{_NOT_BEFORE_HONORIFIC}{PERSON_WORD}){{0,2}}?"
        r"(?=[ \t]+(?i:ji|sahab|behenji|bhenji|didi|babu|amma|bhai)\b)"
    )),
    # "Mohd. Shahid" / "Md. Arif".
    ("PATIENT_NAME", re.compile(rf"\b{_NOT_DOCTOR}(?:Mohd|Md)\.?[ \t]+{PERSON_WORD}")),
    # Nursing note entry: "14:00 - Name Surname - K/C/O ...".
    ("PATIENT_NAME", re.compile(
        rf"(?<=\d\d:\d\d - ){PERSON_WORD}(?:[ \t]+{PERSON_WORD}){{0,3}}(?=[ \t]+-[ \t]+K/C/O\b)"
    )),
    # Address fragments that land in the wrong column of broken exports.
    ("HOUSE", re.compile(r"(?i)\b(?:H\.[ \t]?No\.?|House[ \t]No\.?|Makan[ \t]No\.?)[ \t]*\d+[A-Z]?\b")),
    ("LOCALITY", re.compile(r"\b(?i:mohalla)[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2}")),
    ("INSURANCE_ID", re.compile(r"\bPMJAY-[A-Z]{2}-\d{8,12}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?९१[\s-]?)?[६-९][०-९]{4}[\s-]?[०-९]{5}(?!\d)")),
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
        r"(?:[-/](?:IPD|\d{2,4})|20\d{2}(?=-))?[-/]?\d{5,9}(?![\w/-])"
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

NOTE_ADDRESS = re.compile(r"(?im)^([ \t]*(?:address(?:[ \t]*\((?:attendant|guardian|relative)\))?|पता|village|ग्राम|गाँव)[ \t]*:[ \t]*)[^\r\n]+")
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

_AGE_KEYS = {"age", "umar", "आयु", "उम्र"}
# finest first; the LAST one is what privacy._quasi treats as the coarse location
_LOC_RANK = {"village": 0, "villagemohalla": 0, "gaon": 0, "गाँव": 0, "ग्राम": 0, "city": 0,
             "mohalla": 0, "locality": 0, "tehsil": 1, "block": 1, "district": 2, "jila": 2, "जिला": 2}

def extract_clues(ref, fields, narrative="", order="dmy"):
    clues = Clues(ref)
    targets = {"PATIENT_NAME": clues.names, "MRN": clues.hospital_ids, "PHONE": clues.phones,
               "RELATIVE_NAME": clues.relatives, "AADHAAR": clues.gov_ids, "ABHA_NUMBER": clues.gov_ids}
    located = []
    for key, value in fields:
        if not isinstance(value, (str, int)) or not str(value).strip():
            continue
        raw = str(value).strip()
        kind = classify_header(key)
        if key.casefold() in {"patient_ref", "hospital_uhid"}:
            kind = "MRN"
        if kind in targets:
            if kind == "MRN" and raw.isdigit():
                raw = ref.file + "|" + raw
            targets[kind].append(raw)
        if key.casefold() in {"gender", "sex"}:
            clues.sex = raw
        norm = _normalize(key)
        if norm.startswith("dob") or norm in {"dateofbirth", "birthdate", "janmtithi"}:
            if (d := parse_date(raw, order)):
                clues.dob = d.isoformat()
        elif norm in _AGE_KEYS and (m := re.match(r"\d{1,3}", raw)):
            clues.age = int(m[0])
        elif norm in _LOC_RANK:
            located.append((_LOC_RANK[norm], raw))
    clues.locations = [v for _, v in sorted(located, key=lambda t: t[0])]
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
    order = detect_order(parsed.text)
    if parsed.kind == "table":
        rows = read_rows(parsed.text, parsed.delimiter)
        header = next(rows, [])
        return [extract_clues(RecordRef(rel, f"row:{i}"), zip(header, row), order=order)
                for i, row in enumerate(rows)]
    if parsed.kind == "json":
        return [extract_clues(RecordRef(rel, loc), json_fields(unit), order=order)
                for loc, unit in json_units(load_json(parsed.text))]
    return [extract_clues(RecordRef(rel, "doc"), [], parsed.text)]