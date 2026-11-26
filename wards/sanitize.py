"""P1: apply P2's decisions and clean content and hidden channels (names, keys, attachments).

Failures raise (ValueError with a short code, csv.Error, RecursionError); the caller quarantines
the file. Nothing here prints or logs.
"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
import hashlib
import hmac
import re
from pathlib import PurePosixPath

from .contracts import Decision, ParsedFile, RecordRef, SanitizeResult
from .detect import (GENERIC_BP_SUBJECTS, HINDI_NAME_LINE, NOTE_ADDRESS, NOTE_DOB, PATTERNS,
                     RELATIVE_LABEL, VISIT_BP_SUBJECT, classify_columns, classify_header)
from .formats import decode, dump_json, json_units, load_json, read_rows, write_rows
from .privacy import age_band, secret

Decisions = dict[RecordRef, Decision]


class _Counter:
    identifiers = 0  # running total; sanitize_file reports the difference for one file


_count = _Counter()


def _patient_id(decisions: Decisions, rel: str, loc: str) -> str | None:
    decision = decisions.get(RecordRef(rel, loc))
    return decision.patient_id if decision else None


# --------------------------------------------------------------------------- text and values

def clean_text(text: str) -> str:
    """Replace detected identifiers with typed placeholders. TODO(team): much more than regex."""
    text, count = RELATIVE_LABEL.subn(r"\g<label>[RELATIVE_NAME]", text)
    _count.identifiers += count
    for kind, rx in PATTERNS:
        text, n = rx.subn(f"[{kind}]" if kind != "NAME" else " [NAME]", text)
        _count.identifiers += n
    return text

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

def clean_value(v, parent_key=""):
    if isinstance(v, str):
        return clean_text(v)
    if isinstance(v, list):
        return [clean_value(x, parent_key) for x in v]
    if isinstance(v, dict):
        # JSON keys can be PII too (for example a dict keyed by patient name)
        cleaned = {}
        for key, value in v.items():
            field = key.strip().casefold()
            patient_context = parent_key in {"patient", "patients"} or v.get("resourceType") == "Patient"
            if field == "birthdate" and v.get("resourceType") == "Patient" and isinstance(value, str):
                # FHIR date permits year-only precision.
                if re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}){0,2}", value):
                    cleaned[key] = value[:4]
                continue
            if field == "dob" and parent_key in {"patient", "patients"} and isinstance(value, str) and value:
                cleaned[key] = "[DOB]"
                continue
            if parent_key == "address" and field in {"postalcode", "pin", "city", "village"} and isinstance(value, str) and value:
                if field in {"postalcode", "pin"}:
                    cleaned[key] = "[POSTCODE]"
                else:
                    cleaned[key] = clean_text(v["district"]) if isinstance(v.get("district"), str) and v["district"] else "[LOCALITY]"
                continue
            if classify_header(key) == "PATIENT_NAME" or (field == "name" and patient_context):
                cleaned[clean_text(key)] = clean_person_name(value, "[PATIENT_NAME]")
            elif (parent_key.strip("_").casefold() in {"export_meta", "metadata"}
                  and field in {"source_path", "sourcepath"} and isinstance(value, str) and value):
                cleaned[clean_text(key)] = "[SOURCE_PATH]"
            elif field == "notes" and parent_key == "visits" and isinstance(value, str):
                subject = VISIT_BP_SUBJECT.match(value)
                if subject and subject.group().casefold() not in GENERIC_BP_SUBJECTS:
                    value = "[PATIENT_NAME]" + value[subject.end():]
                    _count.identifiers += 1
                cleaned[key] = clean_text(value)
            elif field == "name" and parent_key == "guardian":
                cleaned[clean_text(key)] = clean_person_name(value, "[RELATIVE_NAME]")
            elif (field == "line" and parent_key == "address") or field == "address_note":
                cleaned[clean_text(key)] = clean_person_name(value, "[ADDRESS]")
            elif parent_key == "raised_by" and field == "name" and isinstance(value, str) and value.strip():
                cleaned[clean_text(key)] = "[CONTACT_NAME]"
                _count.identifiers += 1
            elif field == "data" and str(v.get("contentType", "")).split(";")[0].strip().lower() == "text/plain":
                if not isinstance(value, str):
                    raise ValueError("invalid_attachment")
                payload = base64.b64decode("".join(value.split()), validate=True)
                decoded = decode(payload)
                if decoded is None:
                    raise ValueError("undecodable_attachment")
                cleaned[key] = base64.b64encode(clean_text(decoded).encode("utf-8")).decode("ascii")
            elif field == "patient_ref" and isinstance(value, str) and value.strip():
                cleaned[clean_text(key)] = "[PATIENT_REF]"
                _count.identifiers += 1
            else:
                cleaned[clean_text(key)] = clean_value(value, field)
        return cleaned
    return v  # numbers, booleans, null keep their type

# --------------------------------------------------------------------------- file names
def clean_filename(rel: str) -> str | None:
    """A neutral file name when the original holds personal data, else None."""
    path = PurePosixPath(rel)
    # Treat filename separators as boundaries for the existing identifier detectors.
    stem = path.stem.replace("_", " ")
    sensitive = re.search(r"(?i)^discharge[ -]+summary[ -]+\S", stem)
    if not sensitive and not any(rx.search(stem) for kind, rx in PATTERNS if kind in {"MRN", "PHONE", "AADHAAR", "PAN", "EMAIL"}):
        return None
    token = hmac.new(secret(), b"filename|" + rel.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    return f"file_{token}{path.suffix}"

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
    field_types = classify_columns(header)
    labels = [name.strip().casefold() for name in header]
    district = next((i for i, name in enumerate(labels) if name in {"district", "jila", "जिला"}), None)
    add_reference = any(ref.file == rel and d.patient_id for ref, d in decisions.items()) and "PATIENT_NAME" not in field_types
    cleaned_rows = [header + ["patient_pseudonym"] if add_reference else header]
    for i, row in enumerate(rows):
        pid = _patient_id(decisions, rel, f"row:{i}")
        cleaned, redacted = sanitize_row(row, field_types, pid)
        generalized = False
        for col, (label, value) in enumerate(zip(labels, row)):
            if not value.strip():
                continue
            if label in {"village/mohalla", "village", "gaon", "गाँव", "ग्राम"} or (label == "city" and district is not None):
                cleaned[col] = cleaned[district] if district is not None and district < len(cleaned) and cleaned[district] else "[LOCALITY]"
            elif label in {"pin", "pin code", "pincode", "zip", "postal code"}:
                cleaned[col] = "[POSTCODE]"
            elif label in {"dob", "date of birth", "janm tithi"} or label.startswith("dob ("):
                cleaned[col] = "[DOB]"
            elif label in {"age", "umar"} and (match := re.fullmatch(r"(\d{1,3})(?:\s*(?:years?|yrs?|वर्ष))?", value.strip(), re.I)):
                cleaned[col] = age_band(int(match[1]))
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

def redact_bundle_mentions(bundle):
    """Use declared patient names to clean human-readable fields in this bundle."""
    names = set()
    for entry in bundle.get("entry") or []:
        resource = entry.get("resource") if isinstance(entry, dict) else None
        if not isinstance(resource, dict) or resource.get("resourceType") != "Patient":
            continue
        for name in resource.get("name") or []:
            if isinstance(name, dict):
                full = name.get("text")
                if isinstance(full, str) and full.strip():
                    names.add(full.strip())
                given = name.get("given", [])
                family = name.get("family")
                if isinstance(given, list) and all(isinstance(n, str) for n in given) and isinstance(family, str) and given:
                    names.add(" ".join([*given, family]).strip())
    if not names:
        return
    alternatives = "|".join(re.escape(n) for n in sorted(names, key=lambda n: (-len(n), n)) if n)
    if not alternatives:
        return
    pattern = re.compile(r"(?<!\w)(?:" + alternatives + r")(?!\w)", re.I)

    def replace(text):
        cleaned, count = pattern.subn("[PATIENT_NAME]", text)
        _count.identifiers += count
        return cleaned

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            for field, value in node.items():
                if field == "display" and isinstance(value, str):
                    node[field] = replace(value)
                elif field == "div" and isinstance(value, str) and pattern.search(value):
                    try:
                        root = ET.fromstring(value)
                    except ET.ParseError as exc:
                        raise ValueError("invalid_narrative") from exc
                    for element in root.iter():
                        if element.text:
                            element.text = replace(element.text)
                        if element.tail:
                            element.tail = replace(element.tail)
                    node[field] = ET.tostring(root, encoding="unicode")
                elif field == "data" and node.get("contentType") == "text/plain" and isinstance(value, str):
                    raw = base64.b64decode("".join(value.split()), validate=True)
                    decoded = decode(raw)
                    if decoded is None:
                        raise ValueError("undecodable_attachment")
                    node[field] = base64.b64encode(replace(decoded).encode("utf8")).decode("ascii")
                else:
                    visit(value)
    visit(bundle)


def _clean_json(parsed: ParsedFile, decisions: Decisions) -> tuple[str, list[dict], int]:
    data = load_json(parsed.text)
    if isinstance(data, dict) and data.get("resourceType") == "Bundle":
        redact_bundle_mentions(data)
    records = []
    for loc, unit in json_units(data):
        pid = _patient_id(decisions, parsed.rel, loc)
        if pid and isinstance(unit, dict):
            if unit.get("resourceType") == "Bundle":
                unit["identifier"] = {"system": "urn:secret-wards:pseudonym", "value": pid}
            else:
                unit["patient_pseudonym"] = pid
        records.append({"loc": loc, "patient": pid})
    return dump_json(clean_value(data)), records, 0

def _clean_document(parsed: ParsedFile, decisions: Decisions) -> tuple[str, list[dict], int]:
    pid = _patient_id(decisions, parsed.rel, "doc")
    text = redact_declared_names(parsed.text)
    text, addresses = NOTE_ADDRESS.subn(r"\g<1>[ADDRESS]", text)
    text, births = NOTE_DOB.subn(r"\g<1>[DOB]", text)
    text = (f"Patient: {pid}\n" if pid else "") + clean_text(text)
    return text, [{"loc": "doc", "patient": pid}], int(bool(addresses or births))

_CLEANERS = {"table": _clean_table, "json": _clean_json, "text": _clean_document}


def sanitize_file(parsed: ParsedFile, decisions: Decisions) -> SanitizeResult:
    """Clean one file. Counts cover only files that were cleaned successfully."""
    before = _count.identifiers
    new_name = clean_filename(parsed.rel)
    text, records, generalized = _CLEANERS[parsed.kind](parsed, decisions)
    return SanitizeResult(
        text=text,
        records=records,
        identifiers_detected=_count.identifiers - before,
        records_generalized=generalized,
        new_name=new_name,
    )
