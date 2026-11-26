"""P2: pseudonyms, per-patient date shifts, age bands and rare-combination suppression.

The secret is read from RAKSHA_SECRET at call time (never at import) and is required: a missing
or empty secret raises instead of silently producing guessable IDs. It is never printed, logged
or written.

A different secret gives different pseudonyms. Date shifts come from the same secret but live in a
limited range (default 360 values), so ONE patient can get the same offset under two secrets by
chance; across many patients the shifts differ. What matters for utility is that one patient and
one secret always give one offset, so the gap between that patient's dates is preserved.

A PseudonymBook belongs to one pipeline run. It remembers the secret it was created under and
refuses to hand out IDs if the secret changes, so a stale ID can never leak across a rotation.
"""
from __future__ import annotations


import datetime as dt
import hashlib
import hmac
import os
from collections import defaultdict
from pathlib import Path

from .contracts import Clues, Decision, RecordRef

ROOT = Path(__file__).resolve().parent.parent


def _coerce(v: str):
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def load_policy(path: Path) -> dict:
    """Tiny `key: value` reader for config/policy.yaml (no PyYAML needed)."""
    policy: dict = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" in line:
                k, v = (x.strip() for x in line.split(":", 1))
                policy[k] = _coerce(v)
    return policy


POLICY = load_policy(ROOT / "config" / "policy.yaml")


def secret() -> bytes:
    """The run's secret. Raises (without echoing anything) when it is missing or blank."""
    s = os.environ.get("RAKSHA_SECRET", "")
    if not s.strip():
        raise RuntimeError("RAKSHA_SECRET is not set")
    return s.encode()


# --------------------------------------------------------------------------- pseudonyms
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U


def pseudonym(key: str, attempt: int = 0) -> str:
    """Keyed HMAC-SHA256 fake ID. attempt > 0 is only used to resolve a rare collision."""
    msg = key if attempt == 0 else f"{key}|{attempt}"
    digest = hmac.new(secret(), msg.encode("utf-8"), hashlib.sha256).digest()
    n = int.from_bytes(digest[:5], "big")
    code = "".join(_ALPHABET[(n >> (5 * i)) & 31] for i in range(6))
    return f"PSN-{code}"


class PseudonymBook:
    """One fake ID per cluster key, guaranteed unique across keys (30-bit IDs can collide)."""

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}
        self._owner: dict[str, str] = {}
        self._fp = self._fingerprint()

    @staticmethod
    def _fingerprint() -> bytes:
        """Digest of the secret, kept only in memory, to notice a rotation."""
        return hashlib.sha256(b"book|" + secret()).digest()

    def get(self, key: str) -> str:
        if self._fingerprint() != self._fp:
            raise RuntimeError("secret_changed")
        if key in self._by_key:
            return self._by_key[key]
        for attempt in range(10_000):
            pid = pseudonym(key, attempt)
            if self._owner.get(pid, key) == key:
                self._by_key[key] = pid
                self._owner[pid] = key
                return pid
        raise RuntimeError("pseudonym_space_exhausted")

    def assign_all(self, keys) -> None:
        """Assign in sorted order so collision resolution never depends on file order."""
        for k in sorted(set(keys)):
            self.get(k)


# --------------------------------------------------------------------------- dates and ages
def date_shift_days(patient_key: str) -> int:
    """Per-patient shift in [-max, max-1], never 0. Same key -> same shift for every date."""
    m = int(POLICY.get("date_shift_max_days", 180))
    d = hmac.new(secret(), b"shift|" + patient_key.encode("utf-8"), hashlib.sha256).digest()
    v = int.from_bytes(d[:4], "big") % (2 * m) - m
    return v if v != 0 else 1


def shift_date(value: dt.date, patient_key: str) -> dt.date:
    return value + dt.timedelta(days=date_shift_days(patient_key))


def age_band(age: int) -> str:
    """Bands of age_band_years; the band always CONTAINS the true age."""
    w = max(1, int(POLICY.get("age_band_years", 5)))
    lo = (age // w) * w
    return f"{lo}-{lo + w - 1}"

def age_label(age: int, widen: int = 1) -> str:
    """Truthful band that contains `age`; very old ages are top-coded as '85+'."""
    w = max(1, int(POLICY.get("age_band_years", 5))) * max(1, widen)
    top = int(POLICY.get("age_top_code", 85))
    if age >= top:
        return f"{top}+"
    lo = (age // w) * w
    return f"{lo}-{min(lo + w - 1, top - 1)}"

# --------------------------------------------------------------------------- suppression
def _fallback_key(ref: RecordRef) -> str:
    return f"rec|{ref.file}|{ref.loc}"


def _quasi(c: Clues):
    """(age band, sex, coarsest location). None parts mean 'not present'."""
    w = max(1, int(POLICY.get("age_band_years", 5)))
    band = None
    if c.age is not None and c.age >= 0:
        band = c.age // w
    elif c.dob and len(c.dob) >= 4 and c.dob[:4].isdigit():
        # a birth year is NOT an age: convert it, otherwise it lands in a different
        # numeric range than ages and the same people split into two groups
        band = (dt.date.today().year - int(c.dob[:4])) // w
    loc = c.locations[-1].strip().casefold() if c.locations else None
    if band is None and not loc:
        return (None, None, None)   # sex alone is not a quasi-identifier
    return (band, c.sex, loc or None)


def rare_refs(items: list[tuple[str | None, Clues]]) -> set[RecordRef]:
    """Records whose (age band, sex, location) combination covers fewer than min_group_size
    KNOWN patients (k-anonymity on the quasi-identifier tuple).

    Only distinct non-None patient keys count. Unlinked records (key None) may all be one person,
    so they never add to a group's size: five unlinked visits of the same age band are NOT five
    patients, and the whole group is flagged. This is deliberately conservative."""
    k = int(POLICY.get("min_group_size", 5))
    if k <= 1 or not int(POLICY.get("suppress_rare", 1)):
        return set()
    known: dict[tuple, set[str]] = defaultdict(set)
    for key, c in items:
        q = _quasi(c)
        if q != (None, None, None):
            known[q]  # make sure the group exists even when it has no known patient
            if key:
                known[q].add(key)
    rare = {q for q, who in known.items() if len(who) < k}
    return {c.ref for _, c in items if _quasi(c) in rare}


# --------------------------------------------------------------------------- decisions
def decide(key: str | None, clues: Clues, book: PseudonymBook, suppress: bool = False) -> Decision:
    """Everything P1's sanitizer needs for ONE record.

    `book` is required: create one PseudonymBook per pipeline run and pass it to every call.
    Records with no patient key get no fake ID but still get a date shift, derived from the
    record's own locator so it stays deterministic.
    """
    shift_key = key or _fallback_key(clues.ref)
    return Decision(
        ref=clues.ref,
        patient_id=book.get(key) if key else None,
        shift_days=date_shift_days(shift_key),
        age_band_years=max(1, int(POLICY.get("age_band_years", 5))),
        location_level=str(POLICY.get("location_level", "district")),
        suppress=suppress,
    )