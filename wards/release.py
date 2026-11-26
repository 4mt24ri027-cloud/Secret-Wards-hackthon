"""P2: safe output paths, sanitized-file writing, report.json and records.jsonl.

Nothing here ever receives or prints personal data. Reasons are short identifiers.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"|?*\\]')


@dataclass
class Stats:
    identifiers_detected: int = 0
    records_generalized: int = 0
    records_suppressed: int = 0


def reason_of(exc: BaseException) -> str:
    """A quarantine reason that can never contain file content."""
    if isinstance(exc, ValueError) and str(exc) in {
        "unsupported_format", "empty_file", "undecodable_text", "invalid_attachment",
        "undecodable_attachment", "path_escape",
    }:
        return str(exc)
    return type(exc).__name__


def safe_rel(name: str, taken: set[str]) -> str:
    """Relative output path that cannot escape sanitized/, is unique (case-insensitively)."""
    parts: list[str] = []
    for p in name.replace("\\", "/").split("/"):
        p = _BAD_CHARS.sub("_", p).strip()
        if p in ("", ".", ".."):
            continue
        parts.append(p[:120])
    base = "/".join(parts) or "file"
    cand, n = base, 1
    pp = PurePosixPath(base)
    while cand.casefold() in taken:
        n += 1
        cand = str(pp.with_name(f"{pp.stem}_{n}{pp.suffix}"))
    taken.add(cand.casefold())
    return cand


def choose_rel(rel: str, new_name: str | None) -> str:
    """Apply P1's rename. A bare name keeps the original folder."""
    if not new_name:
        return rel
    if "/" in new_name.replace("\\", "/"):
        return new_name
    parent = PurePosixPath(rel).parent
    return new_name if str(parent) == "." else f"{parent}/{new_name}"


def write_sanitized(out: Path, rel: str, text: str) -> None:
    root = (out / "sanitized").resolve()
    dest = (root / rel).resolve()
    if root != dest and root not in dest.parents:
        raise ValueError("path_escape")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="")


def peak_rss_mb() -> float:
    try:
        import resource
        r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(r / 1024 if sys.platform != "darwin" else r / 1048576, 1)
    except Exception:  # noqa: BLE001 - not available on every OS
        return 0.0


def write_release(out: Path, files: list[dict], records: list[dict], stats: Stats, seconds: float) -> None:
    """files:   one dict per input file {input_sha256, output, status[, reason]}
    records: {file, loc, patient} rows; rows of files that ended up quarantined are dropped."""
    exported = {e["output"] for e in files if e.get("output")}
    kept = [r for r in records if r["file"] in exported]
    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in kept:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    n_san = sum(e["status"] == "sanitized" for e in files)
    report = {
        "schema": "raksha-report/1",
        "files": files,
        "counts": {
            "files_total": len(files), "files_sanitized": n_san, "files_quarantined": len(files) - n_san,
            "records_processed": len(kept), "identifiers_detected": stats.identifiers_detected,
            "records_linked": sum(r["patient"] is not None for r in kept),
            "records_generalized": stats.records_generalized,
            "records_suppressed": stats.records_suppressed,
            "records_quarantined": 0,
        },
        "timing": {"seconds": round(seconds, 2)},
        "resources": {"peak_rss_mb": peak_rss_mb()},
    }
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


# kept so main.py can catch everything a reader may raise
READ_ERRORS = (ValueError, RecursionError, UnicodeError, csv.Error, KeyError, IndexError, TypeError,
               AttributeError, OSError)
