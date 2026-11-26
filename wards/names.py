"""P1: names declared in structured fields, redacted wherever else they appear.

Everything is learned from the current input at run time; no names are stored in the code.
Full names apply across the whole release. A single-word name applies only inside the file
that declared it, so a common word elsewhere is left alone.
"""
from __future__ import annotations

import re

from .contracts import ParsedFile
from .detect import classify_columns, classify_header
from .formats import load_json, read_rows

Names = dict[str, str]  # casefolded name -> placeholder

_LETTERS = r"[^\W\d_]|[\u0900-\u0963]"
_WORD = rf"(?:{_LETTERS})(?:{_LETTERS}|['’.-])*"
_NAME_SHAPE = re.compile(rf"{_WORD}(?: {_WORD}){{0,4}}")
_NOT_NAMES = {"unknown", "patient", "baby", "mother", "father", "male", "female", "self",
              "none", "null", "na", "doctor", "nurse"}


def _add(found: Names, value, placeholder: str) -> None:
    if not isinstance(value, str):
        return
    name = " ".join(value.split())
    words = name.casefold().split()
    if len(name) < 3 or not _NAME_SHAPE.fullmatch(name) or _NOT_NAMES.intersection(words):
        return
    key = name.casefold()
    if found.get(key) != "[PATIENT_NAME]":
        found[key] = placeholder


def _add_human_name(found: Names, value, placeholder: str) -> None:
    """A plain string, a FHIR HumanName, a {first, last} object, or a list of these."""
    for item in value if isinstance(value, list) else [value]:
        if isinstance(item, str):
            _add(found, item, placeholder)
        elif isinstance(item, dict):
            _add(found, item.get("text"), placeholder)
            given = item.get("given", item.get("first"))
            given = " ".join(g for g in given if isinstance(g, str)) if isinstance(given, list) else given
            family = item.get("family", item.get("last"))
            if isinstance(given, str) and isinstance(family, str):
                _add(found, f"{given} {family}", placeholder)


def json_names(data) -> Names:
    found: Names = {}
    stack = [data]  # iterative: exports can be nested very deeply
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
            continue
        if not isinstance(node, dict):
            continue
        stack.extend(node.values())
        if node.get("resourceType") == "Patient":
            _add_human_name(found, node.get("name"), "[PATIENT_NAME]")
            for contact in node.get("contact") or []:
                if isinstance(contact, dict):
                    _add_human_name(found, contact.get("name"), "[RELATIVE_NAME]")
            for extension in node.get("extension") or []:
                if isinstance(extension, dict) and "name" in str(extension.get("url", "")).casefold():
                    _add(found, extension.get("valueString"), "[RELATIVE_NAME]")
        for key, value in node.items():
            kind = classify_header(key)
            if kind in {"PATIENT_NAME", "RELATIVE_NAME"}:
                _add_human_name(found, value, f"[{kind}]")
            elif key.casefold() == "patient":
                _add_human_name(found, value.get("name") if isinstance(value, dict) else value,
                                "[PATIENT_NAME]")
            elif key.casefold() == "guardian" and isinstance(value, dict):
                _add_human_name(found, value.get("name"), "[RELATIVE_NAME]")

    return found


def declared_names(parsed: ParsedFile) -> Names:
    """Names that a structured field in this file identifies as a patient or relative."""
    found: Names = {}
    if parsed.kind == "table":
        rows = read_rows(parsed.text, parsed.delimiter)
        kinds = classify_columns(next(rows, []))
        for row in rows:
            for kind, value in zip(kinds, row):
                if kind in {"PATIENT_NAME", "RELATIVE_NAME"}:
                    _add(found, value, f"[{kind}]")
    elif parsed.kind == "json":
        return json_names(load_json(parsed.text))
    return found


class Redactor:
    """Replace known names in free text, leaving a doctor of the same name in place."""

    def __init__(self, names: Names):
        self.names = names
        ordered = sorted(names, key=lambda n: (-len(n), n))
        body = "|".join(r"[ \t]+".join(map(re.escape, name.split())) for name in ordered)
        self.pattern = re.compile(
            rf"(?<![^\W_])(?<![\u0900-\u0963])(?:{body})(?![^\W_])(?![\u0900-\u0963])",
            re.IGNORECASE) if ordered else None

    def apply(self, text: str) -> tuple[str, int]:
        if self.pattern is None:
            return text, 0
        count = 0

        def replace(match):
            nonlocal count
            if re.search(r"(?i)(?:\bdr\.?|डॉ\.?)[ \t]*$", match.string[max(0, match.start() - 8):match.start()]):
                return match[0]
            placeholder = self.names.get(" ".join(match[0].casefold().split()))
            if placeholder is None:
                return match[0]
            count += 1
            return placeholder

        return self.pattern.sub(replace, text), count


def full_names(names: Names) -> Names:
    return {name: kind for name, kind in names.items() if " " in name}
