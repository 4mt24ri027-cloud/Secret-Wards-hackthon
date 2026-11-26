"""P1: date parsing and per-record shifting. One shift per record keeps every interval exact."""
from __future__ import annotations

import datetime as dt
import re

_MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_FULL = ["January", "February", "March", "April", "May", "June", "July", "August",
         "September", "October", "November", "December"]
_M = "|".join(_MON)

NUMERIC = re.compile(r"(?<![\d/.\-])(\d{1,2})([/.\-])(\d{1,2})\2((?:19|20)\d{2})(?!\d)")
ISO = re.compile(r"(?<![\d/.\-])((?:19|20)\d{2})([-/.])(\d{2})\2(\d{2})(?!\d)")
TEXT = re.compile(rf"(?i)(?<!\w)(\d{{1,2}})([ \-])((?:{_M})[a-z]*)\2((?:19|20)\d{{2}})(?!\d)")


def detect_order(text: str) -> str:
    """'dmy' or 'mdy' for ambiguous numeric dates in ONE file (default day-first, as in India)."""
    if re.search(r"(?i)mm[/.\-]dd[/.\-]yyyy", text):
        return "mdy"
    if re.search(r"(?i)dd[/.\-]mm[/.\-]yyyy", text):
        return "dmy"
    dmy = mdy = False
    for m in NUMERIC.finditer(text):
        a, b = int(m[1]), int(m[3])
        dmy |= a > 12
        mdy |= b > 12
    return "mdy" if mdy and not dmy else "dmy"


def _pad(n: int, original: str) -> str:
    return str(n).zfill(2) if len(original) == 2 else str(n)


def parse_date(value: str, order: str = "dmy") -> dt.date | None:
    s = value.strip()
    try:
        if m := ISO.match(s):
            return dt.date(int(m[1]), int(m[3]), int(m[4]))
        if m := NUMERIC.match(s):
            day, mon = (m[1], m[3]) if order == "dmy" else (m[3], m[1])
            return dt.date(int(m[4]), int(mon), int(day))
        if m := TEXT.match(s):
            return dt.date(int(m[4]), _MON.index(m[3][:3].lower()) + 1, int(m[1]))
    except ValueError:
        return None
    return None


def shift_dates(text: str, days: int, order: str = "dmy") -> str:
    """Move every date in `text` by `days`, keeping its original layout."""
    if not days or not text:
        return text
    delta = dt.timedelta(days=days)

    def textual(m):
        try:
            new = dt.date(int(m[4]), _MON.index(m[3][:3].lower()) + 1, int(m[1])) + delta
        except ValueError:
            return m[0]
        name = _FULL[new.month - 1] if len(m[3]) > 3 else _FULL[new.month - 1][:3]
        name = name.upper() if m[3].isupper() else name.lower() if m[3].islower() else name
        return f"{_pad(new.day, m[1])}{m[2]}{name}{m[2]}{new.year}"

    def iso(m):
        try:
            new = dt.date(int(m[1]), int(m[3]), int(m[4])) + delta
        except ValueError:
            return m[0]
        return f"{new.year:04d}{m[2]}{new.month:02d}{m[2]}{new.day:02d}"

    def numeric(m):
        day, mon = (m[1], m[3]) if order == "dmy" else (m[3], m[1])
        try:
            new = dt.date(int(m[4]), int(mon), int(day)) + delta
        except ValueError:
            return m[0]
        d, mo = _pad(new.day, day), _pad(new.month, mon)
        first, second = (d, mo) if order == "dmy" else (mo, d)
        return f"{first}{m[2]}{second}{m[2]}{new.year}"

    return NUMERIC.sub(numeric, ISO.sub(iso, TEXT.sub(textual, text)))