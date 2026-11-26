"""P2: decide which records belong to the same patient.

Principles
  * A wrong link costs more than no link. Weak evidence never links.
  * Name alone never links on its own: it needs a DOB, or age + shared location, or a matching relative.
  * Shared phones are shared by families, so a phone match also needs a matching name.
  * Hard conflicts (different DOB, sex or same-type government ID) veto a link.
  * Clustering merges strongest edges first and re-checks the WHOLE cluster before every merge,
    so A~B and B~C can never drag A and C together when A and C contradict each other.

Keys: a record gets a cluster key "C:<file>|<loc>" (the cluster's smallest locator) when it was
linked to at least one other record, OR it carries a strong identifier on its own (ID, phone,
email, DOB). A record with only a name (plus relatives, age, place) that matched nothing returns
None: too weak to call a patient. Set weak_singleton_gets_id: 1 in policy.yaml to give such
records their own private ID instead. The key is unique per cluster by construction, so two
different people can never share a pseudonym, even if they share an ID that was flagged as a conflict.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from .contracts import Clues, RecordRef
from .privacy import POLICY

MAX_BLOCK = 800  # skip pathological blocks (very common names) instead of going quadratic

# --------------------------------------------------------------------------- name handling
HONORIFICS = {
    "mr", "mrs", "ms", "miss", "dr", "shri", "shree", "shrimati", "shreemati", "smt", "sri", "kumari",
    "kumaree", "km", "ji", "jee", "sahab", "sahib", "saheb", "saab", "saahab", "didi", "deedee", "bhai",
    "bhaiya", "bhaaee", "madam", "sir", "baby", "master", "late",
    "श्री", "श्रीमती", "कुमारी", "जी", "साहब", "साहिब", "दीदी", "भाई", "भैया", "डॉ", "डा", "स्व",
}
ALIASES = {
    "mohd": "mohammad", "md": "mohammad", "mohammed": "mohammad", "muhammad": "mohammad",
    "mohamed": "mohammad", "mohamad": "mohammad", "mohmmad": "mohammad", "mohammd": "mohammad",
}
_SPLIT = re.compile(r"[\s.,;:/\\|()\[\]{}\"'`’_\-]+")

_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
    "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
    "ध": "dh", "न": "n", "प": "p", "फ": "f", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "ळ": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "j", "ड़": "d", "ढ़": "dh",
    "फ़": "f", "य़": "y",
}
_VOW = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e",
        "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o"}
_MATRA = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai",
          "ो": "o", "ौ": "au", "ॉ": "o", "ं": "n", "ँ": "n", "ः": "h"}
_NASAL_MARKS = "ंँः"
_VIRAMA, _NUKTA = "्", "़"


def romanize(tok: str) -> str:
    """Rough Devanagari -> Latin for ONE word, with Hindi word-final schwa deletion."""
    out: list[str] = []
    pending = False  # last char was a consonant that still owes its inherent 'a'
    for ch in tok:
        if ch in _CONS:
            if pending:
                out.append("a")
            out.append(_CONS[ch])
            pending = True
        elif ch in _MATRA:
            if ch in _NASAL_MARKS and pending:
                out.append("a")
            out.append(_MATRA[ch])
            pending = False
        elif ch == _VIRAMA:
            pending = False
        elif ch == _NUKTA:
            continue
        elif ch in _VOW:
            if pending:
                out.append("a")
            out.append(_VOW[ch])
            pending = False
        else:
            if pending:
                out.append("a")
                pending = False
            out.append(ch)
    return "".join(out)


def _has_devanagari(s: str) -> bool:
    return any("ऀ" <= c <= "ॿ" for c in s)


def _norm_token(tok: str) -> str:
    t = tok.strip().strip("'’`").casefold()
    if _has_devanagari(t):
        if t in HONORIFICS:
            return t
        t = romanize(t)
    return ALIASES.get(t, t)


def name_tokens(name: str) -> list[str]:
    toks = []
    for raw in _SPLIT.split(name):
        t = _norm_token(raw)
        if not t or t in HONORIFICS or not any(c.isalpha() for c in t):
            continue
        toks.append(t)
    return toks


_SKEL_SUBS = (("ph", "f"), ("sh", "s"), ("ch", "c"), ("kh", "k"), ("gh", "g"), ("th", "t"),
              ("dh", "d"), ("bh", "b"), ("jh", "j"), ("w", "v"), ("z", "j"), ("q", "k"), ("x", "ks"))


def skeleton(t: str) -> str:
    """Consonant skeleton: Mohammad / Mohd / Md all -> 'md'."""
    s = t
    for a, b in _SKEL_SUBS:
        s = s.replace(a, b)
    s = re.sub(r"[aeiouyh]", "", s)
    return re.sub(r"(.)\1+", r"\1", s)


def token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:                   # initial vs full name
        return 0.9 if a[0] == b[0] else 0.0
    r = SequenceMatcher(None, a, b).ratio()
    sa, sb = skeleton(a), skeleton(b)
    if sa == sb and len(sa) >= 2:
        r = max(r, 0.92)
    return r


def name_sim(ta: list[str], tb: list[str]) -> float:
    """Order-insensitive greedy token matching; extra tokens on either side lower the score."""
    if not ta or not tb:
        return 0.0
    pairs = sorted(((token_sim(x, y), i, j) for i, x in enumerate(ta) for j, y in enumerate(tb)),
                   reverse=True)
    used_i: set[int] = set()
    used_j: set[int] = set()
    total = 0.0
    for s, i, j in pairs:
        if s < 0.6:
            break
        if i in used_i or j in used_j:
            continue
        used_i.add(i)
        used_j.add(j)
        total += s
    return total / max(len(ta), len(tb))


# --------------------------------------------------------------------------- identifier handling
def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def norm_phone(s: str) -> str | None:
    d = _digits(s)
    return d[-10:] if len(d) >= 10 else None


def norm_gov(s: str) -> str | None:
    alnum = re.sub(r"[^0-9A-Za-z]", "", s).upper()
    d = _digits(s)
    if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", alnum):
        return "P:" + alnum
    if len(d) == 12 and alnum == d:
        return "A:" + d
    if len(d) == 14 and alnum == d:
        return "B:" + d
    return "O:" + alnum if len(alnum) >= 6 else None


def norm_hid(s: str) -> str | None:
    alnum = re.sub(r"[^0-9A-Za-z]", "", s).upper()
    return alnum if len(alnum) >= 4 and any(c.isdigit() for c in alnum) else None


_SEX = {"m": "M", "male": "M", "man": "M", "boy": "M", "पुरुष": "M", "f": "F", "female": "F",
        "woman": "F", "girl": "F", "महिला": "F", "स्त्री": "F", "o": "O", "other": "O"}


def norm_sex(s: str | None) -> str | None:
    return _SEX.get(s.strip().casefold()) if s else None


def _norm_loc(s: str) -> str:
    t = re.sub(r"[^\wऀ-ॿ ]", "", s.casefold()).strip()
    return romanize(t) if _has_devanagari(t) else t


@dataclass
class _P:
    idx: int
    ref: RecordRef
    names: list[list[str]]
    rels: list[list[str]]
    gov: set
    hid: set
    phone: set
    email: set
    dob: str | None
    sex: str | None
    age: int | None
    locs: set

    @property
    def has_identity(self) -> bool:
        return bool(self.names or self.gov or self.hid or self.phone or self.email or self.dob)

    @property
    def strong(self) -> bool:
        """Evidence that identifies a patient by itself: any ID, contact detail or DOB."""
        return bool(self.gov or self.hid or self.phone or self.email or self.dob)


def _profile(i: int, c: Clues) -> _P:
    return _P(
        idx=i, ref=c.ref,
        names=[t for n in c.names if (t := name_tokens(n))],
        rels=[t for n in c.relatives if (t := name_tokens(n))],
        gov={g for x in c.gov_ids if (g := norm_gov(x))},
        hid={h for x in c.hospital_ids if (h := norm_hid(x))},
        phone={p for x in c.phones if (p := norm_phone(x))},
        email={e.strip().casefold() for e in c.emails if e.strip()},
        dob=c.dob.strip()[:10] if c.dob and c.dob.strip() else None,
        sex=norm_sex(c.sex),
        age=c.age if isinstance(c.age, int) and c.age >= 0 else None,
        locs={l for x in c.locations if (l := _norm_loc(x))},
    )


# --------------------------------------------------------------------------- pair scoring
def _gov_conflict(ga: set, gb: set) -> bool:
    for pre in ("A", "P", "B"):
        x = {g for g in ga if g[0] == pre}
        y = {g for g in gb if g[0] == pre}
        if x and y and not (x & y):
            return True
    return False


def _conflict(a: _P, b: _P) -> bool:
    if a.dob and b.dob and a.dob != b.dob:
        return True
    if a.sex and b.sex and a.sex != b.sex:
        return True
    if _gov_conflict(a.gov, b.gov):
        return True
    if not (a.dob and b.dob) and a.age is not None and b.age is not None and abs(a.age - b.age) > 2:
        return True
    return False


def _best(a: list[list[str]], b: list[list[str]], min_tokens: int = 1) -> float:
    return max((name_sim(x, y) for x in a for y in b if len(x) >= min_tokens and len(y) >= min_tokens),
               default=0.0)


def _evaluate(a: _P, b: _P):
    """Return (score, kind) when a and b may be the same patient, else None."""
    if _conflict(a, b):
        return None
    has_names = bool(a.names and b.names)
    ns = _best(a.names, b.names)
    if a.gov & b.gov and (ns >= 0.5 or not has_names):
        return 4 + ns, "gov"
    if a.hid & b.hid and (ns >= 0.7 or not has_names):
        return 3 + ns, "hid"
    if (a.phone & b.phone or a.email & b.email) and has_names and ns >= 0.85:
        return 2 + ns, "contact"
    # name-based: needs two-token names on both sides plus corroboration
    ns2 = _best(a.names, b.names, min_tokens=2)
    if ns2 < 0.85:
        return None
    rel = _best(a.rels, b.rels) if a.rels and b.rels else None
    if rel is not None and rel < 0.6:
        return None  # different father / husband -> different people
    if a.dob and b.dob and a.dob == b.dob:
        return 1 + ns2, "name"
    if a.age is not None and b.age is not None and a.locs & b.locs:
        return 0.8 + ns2, "name"
    if rel is not None and rel >= 0.85:
        return 0.7 + ns2, "name"
    return None


# --------------------------------------------------------------------------- blocking
def _block_keys(p: _P) -> set:
    keys: set = set()
    keys.update(("g", g) for g in p.gov)
    keys.update(("h", h) for h in p.hid)
    keys.update(("p", x) for x in p.phone)
    keys.update(("e", x) for x in p.email)
    for toks in p.names:
        full = [t for t in toks if len(t) > 1]
        if len(full) >= 2:
            sk = sorted(skeleton(t) for t in full)
            keys.add(("n", sk[0], sk[-1]))
        if full and p.dob:
            keys.add(("d", skeleton(max(full, key=len)), p.dob))
    return keys


# --------------------------------------------------------------------------- clustering
def _agg_ok(A: dict, B: dict) -> bool:
    if A["dob"] and B["dob"] and len(A["dob"] | B["dob"]) > 1:
        return False
    if A["sex"] and B["sex"] and len(A["sex"] | B["sex"]) > 1:
        return False
    return not _gov_conflict(A["gov"], B["gov"])


def _members_consistent(profiles: list[_P], A: dict, B: dict) -> bool:
    for i in A["mem"][:20]:
        for j in B["mem"][:20]:
            pi, pj = profiles[i], profiles[j]
            if _conflict(pi, pj):
                return False
            if pi.names and pj.names and _best(pi.names, pj.names) < 0.7:
                return False
    return True


def link(all_clues: list[Clues]) -> dict[RecordRef, str | None]:
    """Cluster key per record; None when the evidence is too weak (see module docstring)."""
    profiles = [_profile(i, c) for i, c in enumerate(all_clues)]
    n = len(profiles)

    blocks: dict[tuple, list[int]] = defaultdict(list)
    for p in profiles:
        for k in _block_keys(p):
            blocks[k].append(p.idx)

    edges: dict[tuple[int, int], tuple | None] = {}
    for members in blocks.values():
        if len(members) < 2 or len(members) > MAX_BLOCK:
            continue
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                pair = (members[x], members[y])
                if pair not in edges:
                    edges[pair] = _evaluate(profiles[pair[0]], profiles[pair[1]])
    ranked = sorted(((r[0], i, j, r[1]) for (i, j), r in edges.items() if r), key=lambda e: (-e[0], e[1], e[2]))

    parent = list(range(n))
    agg = [{"dob": {p.dob} if p.dob else set(), "sex": {p.sex} if p.sex else set(),
            "gov": set(p.gov), "mem": [p.idx]} for p in profiles]

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _score, i, j, kind in ranked:
        ri, rj = sorted((find(i), find(j)))
        if ri == rj:
            continue
        A, B = agg[ri], agg[rj]
        if not _agg_ok(A, B):
            continue
        if kind == "name" and not _members_consistent(profiles, A, B):
            continue
        parent[rj] = ri
        A["dob"] |= B["dob"]
        A["sex"] |= B["sex"]
        A["gov"] |= B["gov"]
        A["mem"] += B["mem"]

    smallest: dict[int, str] = {}
    size: dict[int, int] = defaultdict(int)
    for p in profiles:
        r = find(p.idx)
        size[r] += 1
        loc = f"{p.ref.file}|{p.ref.loc}"
        if r not in smallest or loc < smallest[r]:
            smallest[r] = loc

    own_id_for_weak = bool(int(POLICY.get("weak_singleton_gets_id", 0)))
    result: dict[RecordRef, str | None] = {}
    for p in profiles:
        r = find(p.idx)
        if size[r] > 1 or p.strong or (own_id_for_weak and p.has_identity):
            result[p.ref] = f"C:{smallest[r]}"
        else:
            result[p.ref] = None  # evidence too weak: a name alone is not a patient
    return result