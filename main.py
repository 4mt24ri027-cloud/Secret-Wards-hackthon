#!/usr/bin/env python3
"""Secret Wards starter: a correct *skeleton*, not a solution.

It already does the boring, contract-critical parts right:
  * walks every input file in a fixed order (deterministic output),
  * decodes UTF-8 / UTF-8-BOM / UTF-16 / cp1252 and writes UTF-8,
  * keeps CSV as CSV (same delimiter, same header), JSON as JSON (same structure),
  * quarantines anything it cannot parse instead of copying it,
  * writes report.json (SHA-256 per input file, honest counts, timing, memory),
  * writes records.jsonl with the right locators (row:N, /json/pointer, doc),
  * gives you keyed HMAC pseudonyms and per-patient date shifting helpers,
  * never prints, logs or stores personal data or RAKSHA_SECRET.

What it does NOT do is the actual challenge. Search for "TODO(team)".
As shipped it is roughly the "naive regex" level: it passes CONTRACT OK and scores low.

Usage: python main.py --input <input dir> --output <empty output dir>
Standard library only, Python 3.10+.
"""
from __future__ import annotations

import base64
import argparse
import csv
import datetime as dt
import hashlib
import hmac
from wards.detect import classify_columns, classify_header
from wards.formats import read_rows, write_rows
from wards.sanitize import sanitize_row
import json
import os
import re
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- policy
from wards.privacy import age_band, POLICY
from wards.contracts import Clues, RecordRef
from wards.linkage import link
from wards.release import Stats as ReleaseStats
from wards.release import choose_rel, reason_of, safe_rel, write_release, write_sanitized

SECRET = os.environ.get("RAKSHA_SECRET", "").encode()  # never print or write this


# --------------------------------------------------------------------------- pseudonyms & dates
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


def pseudonym(patient_key: str) -> str:
    """Stable, non-reversible ID: HMAC-SHA256 keyed with RAKSHA_SECRET (never a plain hash).

    Same key + same secret -> same ID in every file. A different secret -> a different ID.
    patient_key should be YOUR canonical identity for a cluster of records (see link_records).
    """
    digest = hmac.new(SECRET, patient_key.encode("utf-8"), hashlib.sha256).digest()
    n = int.from_bytes(digest[:5], "big")
    code = "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(6))
    return f"PSN-{code}"


def date_shift_days(patient_key: str) -> int:
    """Per-patient shift in [-max, +max], never 0. Shift every date of one patient by the
    SAME amount and a 9-day stay stays 9 days."""
    m = int(POLICY.get("date_shift_max_days", 180))
    d = hmac.new(SECRET, b"shift|" + patient_key.encode("utf-8"), hashlib.sha256).digest()
    v = int.from_bytes(d[:4], "big") % (2 * m) - m
    return v if v != 0 else 1


def shift_date(value: dt.date, patient_key: str) -> dt.date:
    return value + dt.timedelta(days=date_shift_days(patient_key))


def age_band(age: int) -> str:
    """5-year bands by default; the band must CONTAIN the true age."""
    w = int(POLICY.get("age_band_years", 5))
    lo = (age // w) * w
    return f"{lo}-{lo + w - 1}"


# --------------------------------------------------------------------------- detection
# TODO(team): this is the part that wins or loses the event. Ideas, in rough order of value:
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


class Stats:
    identifiers = 0
    records = 0
    linked = 0
    generalized = 0
    suppressed = 0


MRN_PATTERN = next(rx for kind, rx in PATTERNS if kind == "MRN")


def release_filename(rel: str) -> str:
    path = Path(rel)
    # Treat filename separators as boundaries for the existing identifier detectors.
    stem = path.stem.replace("_", " ")
    sensitive = re.search(r"(?i)^discharge[ -]+summary[ -]+\S", stem)
    if not sensitive and not any(rx.search(stem) for kind, rx in PATTERNS if kind in {"MRN", "PHONE", "AADHAAR", "PAN", "EMAIL"}):
        return rel
    token = hmac.new(SECRET, b"filename|" + rel.encode("utf-8"), hashlib.sha256).hexdigest()[:20]
    return choose_rel(rel, f"file_{token}{path.suffix}")


def clean_text(text: str) -> str:
    """Replace detected identifiers with typed placeholders. TODO(team): much more than regex."""
    text, count = RELATIVE_LABEL.subn(r"\g<label>[RELATIVE_NAME]", text)
    Stats.identifiers += count
    for kind, rx in PATTERNS:
        text, n = rx.subn(f"[{kind}]" if kind != "NAME" else " [NAME]", text)
        Stats.identifiers += n
    return text


def clean_person_name(value, placeholder):
    """Keep structured name shapes and replace only name-bearing strings."""
    if isinstance(value, str) and value.strip():
        Stats.identifiers += 1
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
            elif field == "name" and parent_key == "guardian":
                cleaned[clean_text(key)] = clean_person_name(value, "[RELATIVE_NAME]")
            elif (field == "line" and parent_key == "address") or field == "address_note":
                cleaned[clean_text(key)] = clean_person_name(value, "[ADDRESS]")
            elif parent_key == "raised_by" and field == "name" and isinstance(value, str) and value.strip():
                cleaned[clean_text(key)] = "[CONTACT_NAME]"
                Stats.identifiers += 1
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
                Stats.identifiers += 1
            else:
                cleaned[clean_text(key)] = clean_value(value, field)
        return cleaned
    return v  # numbers, booleans, null keep their type


# --------------------------------------------------------------------------- linkage
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


def file_clues(text, ext, rel):
    if ext in (".csv", ".tsv"):
        rows = read_rows(text, "\t" if ext == ".tsv" else ",")
        header = next(rows, [])
        return [extract_clues(RecordRef(rel, f"row:{i}"), zip(header, row)) for i, row in enumerate(rows)]
    if ext == ".json":
        return [extract_clues(RecordRef(rel, loc), json_fields(unit)) for loc, unit in json_units(json.loads(text))]
    return [extract_clues(RecordRef(rel, "doc"), [], text)]


def collect_ids(paths, inp):
    clues = []
    for path in paths:
        ext = path.suffix.lower()
        if ext in {".csv", ".tsv", ".json", ".txt"}:
            try:
                text = decode(path.read_bytes())
                if text:
                    clues.extend(file_clues(text, ext, path.relative_to(inp).as_posix()))
            except (ValueError, RecursionError, csv.Error):
                continue  # The release pass reports the quarantine.
    return {ref: pseudonym(key) for ref, key in link(clues).items() if key}


# --------------------------------------------------------------------------- I/O
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


def process_csv(text: str, delimiter: str, rel: str, records: list, ids=None) -> str:
    rows = read_rows(text, delimiter)
    header = next(rows, None)
    if header is None:
        return ""
    field_types = classify_columns(header)
    labels = [name.strip().casefold() for name in header]
    district = next((i for i, name in enumerate(labels) if name in {"district", "jila", "जिला"}), None)
    add_reference = ids and any(ref.file == rel for ref in ids) and "PATIENT_NAME" not in field_types
    cleaned_rows = [header + ["patient_pseudonym"] if add_reference else header]
    for i, row in enumerate(rows):
        pid = (ids or {}).get(RecordRef(rel, f"row:{i}"))
        cleaned, redacted = sanitize_row(row, field_types, pid, clean_text)
        generalized = False
        for col, (label, value) in enumerate(zip(labels, row)):
            if not value.strip():
                continue
            if label in {"village/mohalla", "village", "gaon", "गाँव"}:
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
        Stats.generalized += generalized
        if add_reference:
            cleaned.append(pid or "")
        elif pid and pid not in cleaned:
            idx = field_types.index("PATIENT_NAME")
            cleaned.extend([""] * max(0, idx + 1 - len(cleaned)))
            cleaned[idx] = pid
        cleaned_rows.append(cleaned)
        Stats.identifiers += redacted
        records.append({"file": f"sanitized/{rel}", "loc": f"row:{i}", "patient": pid})
        Stats.records += 1
        Stats.linked += pid is not None
    return write_rows(cleaned_rows, delimiter)


def process_json(text: str, rel: str, records: list, ids=None) -> str:
    data = json.loads(text)
    for loc, unit in json_units(data):
        pid = (ids or {}).get(RecordRef(rel, loc))
        if pid and isinstance(unit, dict):
            if unit.get("resourceType") == "Bundle":
                unit["identifier"] = {"system": "urn:secret-wards:pseudonym", "value": pid}
            else:
                unit["patient_pseudonym"] = pid
        records.append({"file": f"sanitized/{rel}", "loc": loc, "patient": pid})
        Stats.records += 1
    return json.dumps(clean_value(data), ensure_ascii=False, indent=2) + "\n"


def process_text(text: str, rel: str, records: list, ids=None) -> str:
    pid = (ids or {}).get(RecordRef(rel, "doc"))
    records.append({"file": f"sanitized/{rel}", "loc": "doc", "patient": pid})
    Stats.records += 1
    return (f"Patient: {pid}\n" if pid else "") + clean_text(text)


def main() -> int:
    ap = argparse.ArgumentParser(description="Secret Wards starter pipeline")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    t0 = time.monotonic()
    inp, out = Path(a.input), Path(a.output)
    san = out / "sanitized"
    san.mkdir(parents=True, exist_ok=True)
    files, records = [], []
    taken = set()
    sys.setrecursionlimit(5000)

    paths = sorted(p for p in inp.rglob("*") if p.is_file())
    ids = collect_ids(paths, inp)
    for path in paths:
        rel = path.relative_to(inp).as_posix()
        raw = path.read_bytes()
        entry = {"input_sha256": hashlib.sha256(raw).hexdigest()}
        ext = path.suffix.lower()
        try:
            if ext not in (".csv", ".tsv", ".json", ".txt"):
                raise ValueError("unsupported_format")
            if not raw.strip():
                raise ValueError("empty_file")
            text = decode(raw)
            if text is None:
                raise ValueError("undecodable_text")
            output_rel = safe_rel(release_filename(rel), taken)
            file_records = []
            if ext in (".csv", ".tsv"):
                result = process_csv(text, "\t" if ext == ".tsv" else ",", rel, file_records, ids)
            elif ext == ".json":
                result = process_json(text, rel, file_records, ids)
            else:
                result = process_text(text, rel, file_records, ids)
            write_sanitized(out, output_rel, result)
            output = f"sanitized/{output_rel}"
            records.extend({**row, "file": output} for row in file_records)
            entry.update(output=output, status="sanitized")
        except (ValueError, RecursionError, UnicodeError, csv.Error) as exc:
            # Fail safe: never copy what we could not clean. The reason holds no file content.
            reason = reason_of(exc)
            entry.update(output=None, status="quarantined", reason=reason)
        files.append(entry)

    stats = ReleaseStats(Stats.identifiers, Stats.generalized, Stats.suppressed)
    write_release(out, files, records, stats, time.monotonic() - t0)
    n_san = sum(entry["status"] == "sanitized" for entry in files)
    print(f"files {len(files)} sanitized {n_san} quarantined {len(files) - n_san} records {len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
