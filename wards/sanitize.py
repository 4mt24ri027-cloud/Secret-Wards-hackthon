"""Clean structured records using their column types."""

from collections.abc import Callable


def sanitize_row(
    row: list[str],
    field_types: list[str | None],
    patient_id: str | None,
    clean_text: Callable[[str], str],
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
