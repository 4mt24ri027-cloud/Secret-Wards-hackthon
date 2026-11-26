"""Read and write CSV and TSV hospital records."""

import csv
import io
from collections.abc import Iterable, Iterator


def read_rows(text: str, delimiter: str = ",") -> Iterator[list[str]]:
    """Read decoded text one row at a time, including the header."""
    with io.StringIO(text, newline="") as stream:
        reader = csv.reader(stream, delimiter=delimiter, strict=True)
        yield from reader


def write_rows(rows: Iterable[list[str]], delimiter: str = ",") -> str:
    """Return CSV or TSV text with cell order and values preserved."""
    with io.StringIO(newline="") as stream:
        writer = csv.writer(stream, delimiter=delimiter, lineterminator="\r\n")
        writer.writerows(rows)
        return stream.getvalue()