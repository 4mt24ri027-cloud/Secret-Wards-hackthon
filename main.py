#!/usr/bin/env python3
"""Secret Wards: two-pass orchestration.

Pass 1 reads every file, collects patient clues, links records and makes privacy decisions.
Pass 2 cleans each file with those decisions and writes the release.

Usage: python main.py --input <input dir> --output <empty output dir>
Needs RAKSHA_SECRET. Standard library only, Python 3.10+. Prints counts only.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

from wards.contracts import Decision, RecordRef
from wards.detect import collect_clues
from wards.formats import read_file
from wards.linkage import link
from wards.names import Names, declared_names
from wards.privacy import PseudonymBook, decide, rare_refs
from wards.release import READ_ERRORS, Stats, choose_rel, reason_of, safe_rel, write_release, write_sanitized
from wards.sanitize import sanitize_file

# Errors that quarantine one file instead of stopping the run.
FILE_ERRORS = READ_ERRORS


def collect_names(paths: list[Path], inp: Path) -> Names:
    """Every patient and relative name that a structured field declares, across all files."""
    names: Names = {}
    for path in paths:
        try:
            found = declared_names(read_file(path.relative_to(inp).as_posix(), path.read_bytes()))
        except FILE_ERRORS:
            continue
        for name, kind in found.items():
            if names.get(name) != "[PATIENT_NAME]":
                names[name] = kind
    return names


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
    rare = rare_refs([(keys.get(c.ref), c) for c in clues])
    return {c.ref: decide(keys.get(c.ref), c, book, suppress=c.ref in rare) for c in clues}


def release_files(paths: list[Path], inp: Path, out: Path, decisions: dict[RecordRef, Decision],
                  names: Names | None = None):
    """Pass 2: clean and write every file; never copy one that could not be processed."""
    files, records, taken = [], [], set()
    stats = Stats()
    for path in paths:
        rel = path.relative_to(inp).as_posix()
        raw = path.read_bytes()
        entry = {"input_sha256": hashlib.sha256(raw).hexdigest()}
        try:
            result = sanitize_file(read_file(rel, raw), decisions, names)
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
            stats.records_suppressed += sum(
                1 for row in result.records
                if (decision := decisions.get(RecordRef(rel, row["loc"]))) and decision.suppress
            )
            entry.update(output=output, status="sanitized")
        files.append(entry)
    return files, records, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Secret Wards pipeline")
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args(argv)
    t0 = time.monotonic()
    def runner_path(value, env_key):
        # The kit uses POSIX shell quoting even when launched through Windows cmd.
        supplied = os.environ.get(env_key)
        if os.name == "nt" and supplied and value == "'" + supplied + "'":
            return Path(supplied)
        return Path(value)

    inp, out = runner_path(a.input, "RAKSHA_INPUT"), runner_path(a.output, "RAKSHA_OUTPUT")
    if not inp.is_dir() or inp.resolve() in (out.resolve(), *out.resolve().parents):
        ap.error("use an existing input directory and a separate output directory")
    if out.exists() and any(out.iterdir()):
        ap.error("choose an empty output directory to prevent stale release files")
    sys.setrecursionlimit(5000)
    book = PseudonymBook()  # fails here, before writing anything, if RAKSHA_SECRET is missing
    (out / "sanitized").mkdir(parents=True, exist_ok=True)

    paths = sorted(p for p in inp.rglob("*") if p.is_file())
    decisions = make_decisions(paths, inp, book)
    names = collect_names(paths, inp)
    files, records, stats = release_files(paths, inp, out, decisions, names)
    write_release(out, files, records, stats, time.monotonic() - t0)

    n_san = sum(entry["status"] == "sanitized" for entry in files)
    print(f"files {len(files)} sanitized {n_san} quarantined {len(files) - n_san} records {len(records)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
