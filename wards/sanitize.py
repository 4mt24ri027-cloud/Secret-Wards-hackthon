"""P1: apply P2's decisions and clean content and hidden channels (names, keys, attachments).

Failures raise (ValueError with a short code, csv.Error, RecursionError); the caller quarantines
the file. Nothing here prints or logs.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
from pathlib import PurePosixPath

from .contracts import Decision, ParsedFile, RecordRef, SanitizeResult
from .detect import (GENERIC_BP_SUBJECTS, HINDI_NAME_LINE, NOTE_ADDRESS, NOTE_DOB, PATTERNS, PERSON_NAME,
                     RELATIVE_LABEL, VISIT_BP_SUBJECT, AGE_WITH_UNIT, PATIENT_CUE, table_schema, classify_header)
from .formats import decode, dump_json, json_units, load_json, read_rows, write_rows
from .names import Names, Redactor, declared_names, full_names, json_names
from .dates import detect_order, shift_dates
from .privacy import POLICY, age_label, secret

Decisions = dict[RecordRef, Decision]


class _Counter:
    shift = 0
    widen = 1
    order = "dmy"
    identifiers = 0  # running total; sanitize_file reports the difference for one file


_count = _Counter()
_known = Redactor({})  # names declared in structured fields; replaced for each file


_DOB_KEYS = {"dob", "date_of_birth", "dateofbirth", "date of birth", "birth_date", "birthdate"}
_AGE_FIELDS = {"age", "umar", "आयु", "उम्र"}
_AGE_LABELLED = re.compile(r"(?i)((?:\bage|\baayu|\bumar|आयु|उम्र)[ \t]*[:\-]?[ \t]*)(\d{1,3})(?![\d\-/+]|\.\d)")
_AGE_SEX = re.compile(r"(?<![\d/.\-])(\d{1,3})(?![\d\-+])(?=[ \t]*(?:(?i:yrs?|years?|y)|वर्ष)?[ \t]*/[ \t]*(?i:[MF])\b)")


def band_ages(text):
    def labelled(m):
        age = int(m[2])
        return m[1] + age_label(age, _count.widen) if age <= 120 else m[0]

    def with_sex(m):
        age = int(m[1])
        return age_label(age, _count.widen) if age <= 120 else m[0]

    return _AGE_SEX.sub(with_sex, _AGE_LABELLED.sub(labelled, text))


def _enter(decisions: Decisions, rel: str, loc: str) -> str | None:
    decision = decisions.get(RecordRef(rel, loc))
    _count.shift = decision.shift_days if decision else 0
    _count.widen = int(POLICY.get('rare_age_widen', 4)) if decision and decision.suppress else 1
    return decision.patient_id if decision else None


# --------------------------------------------------------------------------- text and values

def clean_text(text: str, *, keep_day: bool = False) -> str:
    """Replace known names and detected identifiers with typed placeholders."""
    text, count = _known.apply(text)
    _count.identifiers += count
    text, count = RELATIVE_LABEL.subn(r"\g<label>[RELATIVE_NAME]", text)
    _count.identifiers += count
    text, count = PATIENT_CUE.subn(r"\g<label>[PATIENT_NAME]", text)
    _count.identifiers += count
    for kind, rx in PATTERNS:
        text, n = rx.subn(f"[{kind}]" if kind != "NAME" else " [NAME]", text)
        _count.identifiers += n
    return shift_dates(band_ages(text), _count.shift, _count.order, month_only=(_count.widen > 1 and not keep_day))

def clean_person_name(value, placeholder):
    """Keep structured name shapes and replace only name-bearing strings."""
    if isinstance(value, str) and value.strip():
        _count.identifiers += 1
        return placeholder
    if isinstance(value, list):
        return [clean_person_name(item, placeholder) for item in value]
    if isinstance(value, dict):
        parts = {"first", "last", "local", "given", "family", "text", "middle"}
        return {
            clean_text(k): clean_person_name(v, placeholder) if k.casefold() in parts else clean_value(v, k)
            for k, v in value.items()
        }
    return value

def _unique(key: str, taken: dict) -> str:
    """Two redacted keys can look alike; number them so that no value is overwritten."""
    candidate, number = key, 1
    while candidate in taken:
        number += 1
        candidate = f"{key}_{number}"
    return candidate

def _plain_attachment(value, transform):
    if not isinstance(value, str):
        raise ValueError("invalid_attachment")
    payload = base64.b64decode("".join(value.split()), validate=True)
    decoded = decode(payload)
    if decoded is None:
        raise ValueError("undecodable_attachment")
    return base64.b64encode(transform(decoded).encode("utf-8")).decode("ascii")


def redact_bundle_mentions(bundle):
    """Redact declared names in FHIR displays, XHTML narratives and plain-text attachments in place."""
    redactor = Redactor(json_names(bundle))
    if not redactor.names:
        return

    def redact(text):
        return redactor.apply(text)[0]

    stack = [bundle]
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    stack.append(value)
                elif key in {"display", "div"} and isinstance(value, str):
                    node[key] = redact(value)
                elif key == "data" and str(node.get("contentType", "")).partition(";")[0].strip().lower() == "text/plain":
                    node[key] = _plain_attachment(value, redact)


def clean_value(v, parent_key="", *, units=None):
    if units and id(v) in units:
        decisions, rel, loc = units[id(v)]
        _enter(decisions, rel, loc)
        try:
            return _clean_value(v, parent_key)
        finally:
            _count.shift, _count.widen = 0, 1
    return _clean_value(v, parent_key, units)


def _clean_value(v, parent_key, units=None):
    if isinstance(v, str):
        return clean_text(v)
    if isinstance(v, list):
        return [clean_value(x, parent_key, units=units) for x in v]
    if isinstance(v, dict):
        # JSON keys can be PII too (for example a dict keyed by patient name)
        cleaned = {}
        for key, value in v.items():
            field = key.strip().casefold()
            new_key = _unique(clean_text(key), cleaned)
            patient_context = parent_key in {"patient", "patients"} or v.get("resourceType") == "Patient"
            if field == "birthdate" and v.get("resourceType") == "Patient" and isinstance(value, str):
                # FHIR date permits year-only precision.
                if re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}){0,2}", value):
                    cleaned[key] = value[:4]
                continue
            if field in _DOB_KEYS and isinstance(value, str) and value:
                _count.identifiers += 1
                cleaned[new_key] = "[DOB]"
                continue
            if parent_key == "address" and field in {"postalcode", "pin", "city", "village", "district", "tehsil", "block"} and isinstance(value, str) and value:
                if field in {"postalcode", "pin"}:
                    cleaned[key] = "[POSTCODE]"
                elif _count.widen > 1 and int(POLICY.get("rare_drop_district", 1)):
                    cleaned[key] = "[DISTRICT]" if field == "district" else "[LOCALITY]"
                elif field == "district":
                    cleaned[key] = clean_text(value)
                else:
                    cleaned[key] = clean_text(v["district"]) if isinstance(v.get("district"), str) and v["district"] else "[LOCALITY]"
                continue
            kind = classify_header(key)
            if (kind == "AGE" or field in _AGE_FIELDS) and isinstance(value, (int, str)):
                age = str(value).strip()
                match = re.fullmatch(r"(\d{1,3})", age) or AGE_WITH_UNIT.fullmatch(age)
                if match:
                    cleaned[new_key] = age_label(int(match[1]), _count.widen)
                    continue
            if kind == "LOCALITY" and isinstance(value, str) and value.strip():
                cleaned[new_key] = "[LOCALITY]"
            elif kind == "RELATIVE_NAME":
                cleaned[new_key] = clean_person_name(value, "[RELATIVE_NAME]")
            elif kind == "PATIENT_NAME" or (field == "name" and patient_context):
                cleaned[new_key] = clean_person_name(value, "[PATIENT_NAME]")
            elif (parent_key.strip("_").casefold() in {"export_meta", "metadata"}
                  and field in {"source_path", "sourcepath"} and isinstance(value, str) and value):
                cleaned[new_key] = "[SOURCE_PATH]"
            elif field == "notes" and parent_key == "visits" and isinstance(value, str):
                subject = VISIT_BP_SUBJECT.match(value)
                if subject and subject.group().casefold() not in GENERIC_BP_SUBJECTS:
                    value = "[PATIENT_NAME]" + value[subject.end():]
                    _count.identifiers += 1
                cleaned[key] = clean_text(value)
            elif field == "name" and parent_key == "guardian":
                cleaned[new_key] = clean_person_name(value, "[RELATIVE_NAME]")
            elif (field == "line" and parent_key == "address") or field == "address_note":
                cleaned[new_key] = clean_person_name(value, "[ADDRESS]")
            elif parent_key == "raised_by" and field == "name" and isinstance(value, str) and value.strip():
                cleaned[new_key] = "[CONTACT_NAME]"
                _count.identifiers += 1
            elif field == "data" and str(v.get("contentType", "")).split(";")[0].strip().lower() == "text/plain":
                cleaned[key] = _plain_attachment(value, clean_text)
            elif field in {"base64", "attachment", "payload"} and isinstance(value, str) and len(value) >= 16 and len(value.strip()) % 4 == 0:
                try:
                    raw_b = base64.b64decode(value.strip(), validate=True)
                    dec = decode(raw_b)
                    if dec and sum(ch.isprintable() or ch in "\r\n\t" for ch in dec) / max(1, len(dec)) > 0.9:
                        cleaned[new_key] = base64.b64encode(clean_text(dec).encode("utf-8")).decode("ascii")
                    else:
                        cleaned[new_key] = clean_value(value, field, units=units)
                except Exception:
                    cleaned[new_key] = clean_value(value, field, units=units)
            elif (classify_header(key) in {"AADHAAR", "INSURANCE_ID"}
                  and isinstance(value, (str, int)) and str(value).strip()):
                cleaned[new_key] = f"[{classify_header(key)}]"
                _count.identifiers += 1
            elif field == "valuestring" and "name" in str(v.get("url", "")).casefold():
                cleaned[new_key] = clean_person_name(value, "[RELATIVE_NAME]")
            elif field == "patient_ref" and isinstance(value, str) and value.strip():
                cleaned[new_key] = "[PATIENT_REF]"
                _count.identifiers += 1
            else:
                cleaned[new_key] = clean_value(value, field, units=units)
        return cleaned
    return v  # numbers, booleans, null keep their type

# --------------------------------------------------------------------------- file names
def clean_filename(rel: str, known: Redactor | None = None) -> str | None:
    """A neutral file name when the original holds personal data, else None."""
    path = PurePosixPath(rel)
    # Treat filename separators as boundaries for the existing identifier detectors.
    stem = path.stem.replace("_", " ")
    words = re.sub(r"[.\s-]+", " ", stem).strip()
    known_name = known is not None and known.pattern is not None and (
        known.pattern.search(stem) or known.pattern.search(words)
    )
    sensitive = (known_name or re.fullmatch(PERSON_NAME, words)
                 or re.search(r"(?i)^discharge[ -]+summary[ -]+\S", stem))
    if not sensitive and not any(rx.search(stem) for kind, rx in PATTERNS if kind in {"MRN", "PHONE", "AADHAAR", "PAN", "EMAIL"}):
        return None
    token = hmac.new(secret(), b"filename|" + rel.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    return f"file_{token}{path.suffix}"

def clean_header(cells: list[str]) -> list[str]:
    """Headers can hold record numbers and names, e.g. one column per patient."""
    cleaned: dict[str, None] = {}
    for cell in cells:
        text, count = re.subn(r"(\[MRN\][ \t]+)[A-Z][a-z]+(?:[ \t]+[A-Z][a-z]+)*",
                              r"\1[PATIENT_NAME]", clean_text(cell))
        _count.identifiers += count
        cleaned[_unique(text, cleaned) if text != cell else text] = None
    # Unchanged duplicate headers must keep their column count.
    return list(cleaned) if len(cleaned) == len(cells) else [clean_text(cell) for cell in cells]

def redact_declared_names(text):
    names = {match["name"] for match in HINDI_NAME_LINE.finditer(text)}
    for name in sorted(names, key=lambda n: (-len(n), n)):
        words = r"[ \t]+".join(re.escape(word) for word in name.split())
        pattern = rf"(?<![\w\u0900-\u0963]){words}(?![\w\u0900-\u0963])"
        text, count = re.subn(pattern, "[PATIENT_NAME]", text)
        _count.identifiers += count
    return text

# --------------------------------------------------------------------------- per format
def sanitize_row(
    row: list[str],
    field_types: list[str | None],
    patient_id: str | None,
) -> tuple[list[str], int]:
    """Return cleaned cells and the number redacted using header evidence."""
    cleaned = []
    redacted = 0
    for index, value in enumerate(row):
        kind = field_types[index] if index < len(field_types) else None
        if kind and value.strip():
            replacement = patient_id if kind == "PATIENT_NAME" and patient_id else f"[{kind}]"
            cleaned.append(replacement)
            redacted += 1
        else:
            cleaned.append(clean_text(value))
    return cleaned, redacted

def _clean_table(parsed: ParsedFile, decisions: Decisions) -> tuple[str, list[dict], int]:
    rel, delimiter = parsed.rel, parsed.delimiter
    records, generalized_rows = [], 0
    rows = read_rows(parsed.text, delimiter)
    header = next(rows, None)
    if header is None:
        return "", records, 0
    field_types, rows = table_schema(header, rows)
    labels = [name.strip().casefold() for name in header]
    district = next((i for i, name in enumerate(labels) if name in {"district", "jila", "जिला"}), None)
    add_reference = any(ref.file == rel and d.patient_id for ref, d in decisions.items()) and "PATIENT_NAME" not in field_types
    safe_header = clean_header(header)
    cleaned_rows = [safe_header + ["patient_pseudonym"] if add_reference else safe_header]
    for i, row in enumerate(rows):
        pid = _enter(decisions, rel, f"row:{i}")
        cleaned, redacted = sanitize_row(row, field_types, pid)
        generalized = False
        if _count.widen > 1 and int(POLICY.get("rare_drop_district", 1)):
            if district is not None and district < len(cleaned) and cleaned[district]:
                cleaned[district] = "[DISTRICT]"
                generalized = True
        for col, (label, value) in enumerate(zip(labels, row)):
            if not value.strip():
                continue
            if field_types[col] == "LOCALITY" or label in {"village/mohalla", "village", "gaon", "गाँव", "ग्राम"} or (label == "city" and district is not None):
                cleaned[col] = cleaned[district] if district is not None and district < len(cleaned) and cleaned[district] else "[LOCALITY]"
            elif label in {"pin", "pin code", "pincode", "zip", "postal code"}:
                cleaned[col] = "[POSTCODE]"
            elif label in {"dob", "date of birth", "janm tithi"} or label.startswith("dob ("):
                cleaned[col] = "[DOB]"
            elif (field_types[col] == "AGE" or label in _AGE_FIELDS) and (match := (re.fullmatch(r"(\d{1,3})", value.strip()) or AGE_WITH_UNIT.fullmatch(value.strip()))):
                cleaned[col] = age_label(int(match[1]), _count.widen)
            else:
                continue
            generalized = True
        generalized_rows += generalized
        if add_reference:
            cleaned.append(pid or "")
        elif pid and pid not in cleaned:
            idx = field_types.index("PATIENT_NAME")
            cleaned.extend([""] * max(0, idx + 1 - len(cleaned)))
            cleaned[idx] = pid
        cleaned_rows.append(cleaned)
        _count.identifiers += redacted
        records.append({"loc": f"row:{i}", "patient": pid})
    return write_rows(cleaned_rows, delimiter), records, generalized_rows

def _clean_json(parsed: ParsedFile, decisions: Decisions) -> tuple[str, list[dict], int]:
    data = load_json(parsed.text)
    records = []
    units = {}
    generalized = 0
    for loc, unit in json_units(data):
        units[id(unit)] = decisions, parsed.rel, loc
        pid = _enter(decisions, parsed.rel, loc)
        if _count.widen > 1:
            generalized += 1
        if pid and isinstance(unit, dict):
            if unit.get("resourceType") == "Bundle":
                unit["identifier"] = {"system": "urn:secret-wards:pseudonym", "value": pid}
            else:
                unit["patient_pseudonym"] = pid
        records.append({"loc": loc, "patient": pid})
    _count.shift, _count.widen = 0, 1
    return dump_json(clean_value(data, units=units)), records, generalized

STAY_DATE_LINE = re.compile(
    r"^[ \t]*(?:(?:date of (?:admission|discharge)|(?:admission|discharge) date)"
    r"|(?:भर्ती|छुट्टी) की तारीख)[ \t]*:[ \t]*", re.I
)


def _clean_document(parsed: ParsedFile, decisions: Decisions) -> tuple[str, list[dict], int]:
    pid = _enter(decisions, parsed.rel, "doc")
    text = redact_declared_names(parsed.text)
    text, addresses = NOTE_ADDRESS.subn(r"\g<1>[ADDRESS]", text)
    text, births = NOTE_DOB.subn(r"\g<1>[DOB]", text)
    text = "".join(clean_text(line, keep_day=bool(STAY_DATE_LINE.match(line)))
                   for line in text.splitlines(keepends=True))
    text = (f"Patient: {pid}\n" if pid else "") + text
    return text, [{"loc": "doc", "patient": pid}], int(bool(addresses or births))

_CLEANERS = {"table": _clean_table, "json": _clean_json, "text": _clean_document}


def sanitize_file(parsed: ParsedFile, decisions: Decisions,
                  release_names: Names | None = None) -> SanitizeResult:
    """Clean one file. Counts cover only files that were cleaned successfully."""
    global _known
    _known = Redactor({**full_names(release_names or {}), **declared_names(parsed)})
    _count.order = detect_order(parsed.text)
    before = _count.identifiers
    new_name = clean_filename(parsed.rel, _known)
    try:
        text, records, generalized = _CLEANERS[parsed.kind](parsed, decisions)
    finally:
        _count.shift, _count.widen = 0, 1
    return SanitizeResult(
        text=text,
        records=records,
        identifiers_detected=_count.identifiers - before,
        records_generalized=generalized,
        new_name=new_name,
    )
