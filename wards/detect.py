"""P1: field classification, text span patterns and per-record patient clues."""
from __future__ import annotations
from .dates import detect_order, parse_date

import json
import re
import unicodedata
from pathlib import Path
from functools import lru_cache
from itertools import chain, islice

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


@lru_cache(maxsize=2048)
def classify_header(header: str) -> str | None:
    """Return a known field type, or None if the header needs other checks."""
    if kind := _field_types.get(_normalize(header)):
        return kind
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", header)
    words = set(re.findall(r"[a-z]+", spaced.casefold()))
    if words & {"doctor", "provider", "clinician", "drug", "test", "diagnosis", "hospital"}:
        return None
    if words & {"name", "naam", "surname", "forename"}:
        if words & {"guardian", "relative", "father", "mother", "husband", "wife", "spouse", "kin", "attendant"}:
            return "RELATIVE_NAME"
        if words & {"patient", "pt", "beneficiary", "registrant", "subject"}:
            return "PATIENT_NAME"
    if words & {"village", "mohalla", "gaon", "hamlet"}:
        return "LOCALITY"
    if "age" in words and not words & {"gestational", "bone", "onset", "adjusted"}:
        return "AGE"
    return None

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

def table_schema(headers, rows):
    """Use explicit titles in otherwise unlabelled columns as name evidence."""
    sample = list(islice(rows, 64))
    kinds = classify_columns(headers)
    for i, kind in enumerate(kinds):
        if kind is None and re.fullmatch(r"(?:extra|unknown|col(?:umn)?|field)[ _-]*\d*", headers[i], re.I):
            values = [row[i].strip() for row in sample if i < len(row) and row[i].strip()]
            if not values:
                continue
            for inferred, pattern in (("PATIENT_NAME", TITLED_NAME), ("RELATIVE_NAME", RELATIVE_LABEL),
                                      ("AGE", AGE_WITH_UNIT), ("LOCALITY", LABELLED_VILLAGE)):
                if all(pattern.fullmatch(value) for value in values):
                    kinds[i] = inferred
                    break
    return kinds, chain(sample, rows)


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
AGE_WITH_UNIT = re.compile(r"(\d{1,3})\s*(?:years?|yrs?|वर्ष)(?:\s+old)?", re.I)
LABELLED_VILLAGE = re.compile(r"(?:village|gaon|ग्राम)\s*:\s*\S.+", re.I)
TITLED_NAME = re.compile(rf"(?i:Mr|Mrs|Ms)\.?[ \t]+{PERSON_NAME}")
PATIENT_CUE = re.compile(
    rf"(?P<label>\b(?i:pt|patient|mr|mrs|ms)\.?[ \t]*:?[ \t]+)"
    rf"(?!(?i:Dr|Doctor|Mr|Mrs|Ms|BP|ID|Name|No)\b){PERSON_NAME}"
)
# Kinship labels identify a relative even when only a first name is given.
RELATIVE_WORD = rf"(?:{PERSON_WORD}|[ऄ-हक़-ॡ][ऀ-ःऄ-ह़-ॣ]*)"
RELATIVE_LABEL = re.compile(
    rf"(?P<label>(?<![\w/])(?i:[swd]/o|attendant:"
    rf"|पिता का नाम:|पति का नाम:|माता का नाम:|पत्नी का नाम:|माँ का नाम:"
    rf"|(?:(?:father|mother|husband|wife|guardian|spouse)(?:'s)?[ \t]+name)[ \t]*:)[ \t]+)"
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
    # Devanagari house numbers: मकान नं. 123, मकान नम्बर 45
    ("HOUSE", re.compile(r"(?:मकान[ \t]*(?:नं\.?|नम्बर|नंबर)|घर[ \t]*(?:नं\.?|नम्बर|नंबर))[ \t]*\d+[A-Za-z]?")),
    ("LOCALITY", re.compile(r"\b(?i:mohalla)[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2}")),
    # Ward number as locality (not hospital ward context)
    ("LOCALITY", re.compile(r"(?i)(?:ward[ \t]+(?:no\.?[ \t]*)?\d{1,3})\b")),
    ("INSURANCE_ID", re.compile(r"\bPMJAY-[A-Z]{2}-\d{8,12}\b")),
    # Broader insurance IDs: policy numbers, TPA IDs, RSBY, CGHS, ECHS
    ("INSURANCE_ID", re.compile(r"(?i)\b(?:RSBY|CGHS|ECHS|TPA)[-/]?[A-Z0-9]{5,15}\b")),
    ("INSURANCE_ID", re.compile(r"(?i)(?:policy|claim)[ \t]*(?:no\.?|number|id)[ \t]*:?[ \t]*[A-Z0-9]{6,20}\b")),
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
    # Landmark patterns: "near X Mandir", "opp. Y Hospital" etc.
    ("LANDMARK", re.compile(
        r"(?i)\b(?:near|opp\.?|opposite|behind|beside|next[ \t]+to|in[ \t]+front[ \t]+of)"
        r"[ \t]+[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+){0,2}"
        r"(?=[ \t]+(?:mandir|masjid|gurudwara|church|temple|mosque|school|hospital|chowk|nagar|colony|market|marg|road|gali)\b)"
    )),
    ("NAME", re.compile(r"(?i)(?<=name:)\s*[^\n,;|]+")),
]

MRN_PATTERN = next(rx for kind, rx in PATTERNS if kind == "MRN")

NOTE_ADDRESS = re.compile(r"(?im)^([ \t]*(?:address(?:[ \t]*\((?:attendant|guardian|relative)\))?|पता|village|ग्राम|गाँव|ठिकाना|निवास)[ \t]*:[ \t]*)[^\r\n]+")
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
_ICD_RX = re.compile(r"\b([A-Z]\d{2}(?:\.\d{1,2})?)\b")
# finest first; the LAST one is what privacy._quasi treats as the coarse location
_LOC_RANK = {"village": 0, "villagemohalla": 0, "gaon": 0, "गाँव": 0, "ग्राम": 0, "city": 0,
             "mohalla": 0, "locality": 0, "tehsil": 1, "block": 1, "district": 2, "jila": 2, "जिला": 2}

def extract_clues(ref, fields, narrative="", order="dmy", kinds=None):
    clues = Clues(ref)
    targets = {"PATIENT_NAME": clues.names, "MRN": clues.hospital_ids, "PHONE": clues.phones,
               "RELATIVE_NAME": clues.relatives, "AADHAAR": clues.gov_ids, "ABHA_NUMBER": clues.gov_ids}
    located = []
    for index, (key, value) in enumerate(fields):
        if not isinstance(value, (str, int)) or not str(value).strip():
            continue
        raw = str(value).strip()
        kind = kinds[index] if kinds is not None else classify_header(key)
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
        elif (kind == "AGE" or norm in _AGE_KEYS) and (m := re.match(r"\d{1,3}", raw)):
            clues.age = int(m[0])
        elif norm in _LOC_RANK or kind == "LOCALITY":
            located.append((_LOC_RANK.get(norm, 0), raw))
        for icd in _ICD_RX.findall(raw):
            clues.conditions.append(icd)
    clues.locations = [v for _, v in sorted(located, key=lambda t: t[0])]
    if narrative:
        clues.conditions.extend(_ICD_RX.findall(narrative))
    ids = set(MRN_PATTERN.findall(narrative))
    if len(ids) == 1:
        clues.hospital_ids.extend(ids)
    elif len(ids) > 1:
        # A discharge summary can list a patient registration and a visit-only ID.
        # Prefer the explicitly labelled registration if all other IDs are admissions.
        labelled = re.findall(
            r"(?im)^[ \t]*(?:पंजीकरण सं\.?|registration (?:no\.?|number)|UHID|MRN)"
            r"[ \t]*:[ \t]*([^\s,;]+)", narrative,
        )
        patients = {value for value in labelled if value in ids}
        if len(patients) == 1 and all(
            re.match(r"(?i)^(?:ADM|IPD?[-/])", value) for value in ids - patients
        ):
            clues.hospital_ids.extend(patients)
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
        p0 = patients[0]
        identifiers = p0.get("identifier")
        if isinstance(identifiers, list):
            for identifier in identifiers:
                if isinstance(identifier, dict) and MRN_PATTERN.fullmatch(str(identifier.get("value", ""))):
                    fields.append(("MRN", identifier["value"]))
        for nm in p0.get("name") or []:
            if isinstance(nm, dict):
                txt = nm.get("text")
                if not txt:
                    given = nm.get("given") or []
                    given_s = " ".join(g for g in given if isinstance(g, str)) if isinstance(given, list) else str(given)
                    txt = f"{given_s} {nm.get('family') or ''}".strip()
                if txt:
                    fields.append(("Patient Name", txt))
        for tel in p0.get("telecom") or []:
            if isinstance(tel, dict) and tel.get("value"):
                sys_t = str(tel.get("system", "")).casefold()
                if sys_t == "phone":
                    fields.append(("Mobile", tel["value"]))
                elif sys_t == "email":
                    fields.append(("Email", tel["value"]))
        if p0.get("gender"):
            fields.append(("gender", p0["gender"]))
        if p0.get("birthDate"):
            fields.append(("dob", p0["birthDate"]))
        for addr in p0.get("address") or []:
            if isinstance(addr, dict):
                for k in ("district", "city"):
                    if addr.get(k):
                        fields.append((k, addr[k]))
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
        kinds, rows = table_schema(header, rows)
        return [extract_clues(RecordRef(rel, f"row:{i}"), zip(header, row), order=order, kinds=kinds)
                for i, row in enumerate(rows)]
    if parsed.kind == "json":
        return [extract_clues(RecordRef(rel, loc), json_fields(unit), order=order)
                for loc, unit in json_units(load_json(parsed.text))]
    return [extract_clues(RecordRef(rel, "doc"), [], parsed.text)]