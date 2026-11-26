#!/usr/bin/env python3
"""Secret Wards: two-pass orchestration.

Pass 1 reads every file, collects patient clues, links records and makes privacy decisions.
Pass 2 cleans each file with those decisions and writes the release.

Usage: python main.py --input <input dir> --output <empty output dir>
Needs RAKSHA_SECRET. Standard library only, Python 3.10+. Prints counts only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from pathlib import Path

from wards.contracts import Decision, RecordRef
from wards.detect import collect_clues
from wards.formats import read_file
from wards.linkage import link
from wards.privacy import PseudonymBook, decide
from wards.release import Stats, choose_rel, reason_of, safe_rel, write_release, write_sanitized
from wards.sanitize import sanitize_file

# Errors that quarantine one file instead of stopping the run.
FILE_ERRORS = (ValueError, RecursionError, UnicodeError, csv.Error)


def make_decisions(paths: list[Path], inp: Path, book: PseudonymBook) -> dict[RecordRef, Decision]:
    """Pass 1: clues -> clusters -> one Decision per record."""
    clues = []
    for path in paths:
        try:
            parsed = read_file(path.relative_to(inp).as_posix(), path.read_bytes())
            clues.extend(collect_clues(parsed))
        except FILE_ERRORS:
            continue  # pass 2 reports the quarantine
    keys = link(clues)
    book.assign_all(key for key in keys.values() if key)  # order-independent collision handling
    return {c.ref: decide(keys.get(c.ref), c, book) for c in clues}


def release_files(paths: list[Path], inp: Path, out: Path, decisions: dict[RecordRef, Decision]):
    """Pass 2: clean and write every file; never copy one that could not be processed."""
    files, records, taken = [], [], set()
    stats = Stats()
    for path in paths:
        rel = path.relative_to(inp).as_posix()
        raw = path.read_bytes()
        entry = {"input_sha256": hashlib.sha256(raw).hexdigest()}
        try:
            result = sanitize_file(read_file(rel, raw), decisions)
            output_rel = safe_rel(choose_rel(rel, result.new_name), taken)
            write_sanitized(out, output_rel, result.text)
        except FILE_ERRORS as exc:
            # Fail safe. The reason is a short code and holds no file content.
            entry.update(output=None, status="quarantined", reason=reason_of(exc))
        else:
            output = f"sanitized/{output_rel}"
            records.extend({"file": output, **row} for row in result.records)
            stats.identifiers_detected += result.identifiers_detected
            stats.records_generalized += result.records_generalized
            entry.update(output=output, status="sanitized")
        files.append(entry)
    return files, records, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Secret Wards pipeline")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    inp, out = Path(a.input), Path(a.output)
    sys.setrecursionlimit(5000)
    book = PseudonymBook()  # fails here, before writing anything, if RAKSHA_SECRET is missing
    (out / "sanitized").mkdir(parents=True, exist_ok=True)

    paths = sorted(p for p in inp.rglob("*") if p.is_file())
    decisions = make_decisions(paths, inp, book)
    files, records, stats = release_files(paths, inp, out, decisions)
    write_release(out, files, records, stats, time.monotonic() - t0)

    n_san = sum(entry["status"] == "sanitized" for entry in files)
    print(f"files {len(files)} sanitized {n_san} quarantined {len(files) - n_san} records {len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
