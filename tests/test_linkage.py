import datetime as dt
import json

import pytest

from main import make_decisions
from wards.contracts import Clues, RecordRef
from wards.formats import read_file
from wards.linkage import link
from wards.privacy import (PseudonymBook, age_band, date_shift_days, decide, pseudonym, rare_refs,
                           shift_date)
from wards.sanitize import sanitize_file


def rec(n, **fields):
    return Clues(ref=RecordRef(f"hospital_{n}.csv", "row:0"), **fields)


def same_patient(a, b):
    result = link([a, b])
    return result[a.ref] is not None and result[a.ref] == result[b.ref]


def test_shared_id_links_but_name_alone_is_uncertain():
    a = Clues(
        ref=RecordRef("hospital_a.csv", "row:0"),
        names=["Mahesh Chauhan"],
        gov_ids=["SYNTHETIC-ID-001"],
    )
    b = Clues(
        ref=RecordRef("hospital_b.csv", "row:0"),
        names=["M. Chauhan"],
        gov_ids=["SYNTHETIC-ID-001"],
    )
    c = Clues(
        ref=RecordRef("hospital_c.csv", "row:0"),
        names=["Mahesh Chauhan"],
    )

    result = link([a, b, c])

    assert result[a.ref] is not None
    assert result[a.ref] == result[b.ref]
    assert result[c.ref] is None


def test_pipeline_links_csv_json_and_note(tmp_path):
    sources = {
        "a.csv": "UHID,Dose\nUHID-012345,650 mg\n",
        "b.json": '{"visits":[{"patient_ref":"UHID-012345"}]}',
        "c.txt": "Seen under UHID-012345.",
    }
    for name, text in sources.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    decisions = make_decisions(sorted(tmp_path.iterdir()), tmp_path, PseudonymBook())
    results = {name: sanitize_file(read_file(name, text.encode()), decisions) for name, text in sources.items()}
    pid = results["a.csv"].records[0]["patient"]
    assert pid.startswith("PSN-")
    assert all(r["patient"] == pid for result in results.values() for r in result.records)
    assert pid in results["a.csv"].text and pid in results["c.txt"].text
    assert json.loads(results["b.json"].text)["visits"][0]["patient_pseudonym"] == pid


# --------------------------------------------------------------------------- same name
def test_same_name_and_dob_is_one_patient():
    assert same_patient(rec("a", names=["Mahesh Chauhan"], dob="1977-04-12"),
                        rec("b", names=["Chauhan Mahesh"], dob="1977-04-12"))


@pytest.mark.parametrize(("first", "second"), [
    ({"dob": "1977-04-12"}, {"dob": "1990-01-30"}),
    ({"gov_ids": ["1111 2222 3333"]}, {"gov_ids": ["4444 5555 6666"]}),
    ({"sex": "M", "age": 40, "locations": ["Rampur"]}, {"sex": "F", "age": 40, "locations": ["Rampur"]}),
    ({"relatives": ["Naresh Chauhan"], "age": 40, "locations": ["Rampur"]},
     {"relatives": ["Suresh Yadav"], "age": 40, "locations": ["Rampur"]}),
    ({}, {}),  # a name alone is never enough
], ids=["different-dob", "different-gov-id", "different-sex", "different-relative", "name-only"])
def test_same_name_different_people_are_never_merged(first, second):
    assert not same_patient(rec("a", names=["Mahesh Chauhan"], **first),
                            rec("b", names=["Mahesh Chauhan"], **second))


# --------------------------------------------------------------------------- secret rotation
def test_same_secret_is_stable_and_new_secret_changes_ids_and_shifts(monkeypatch):
    keys = [f"patient-{i}" for i in range(50)]
    ids = [pseudonym(k) for k in keys]
    shifts = [date_shift_days(k) for k in keys]
    assert ids == [pseudonym(k) for k in keys]
    monkeypatch.setenv("RAKSHA_SECRET", "rotated-secret")
    assert all(old != pseudonym(k) for old, k in zip(ids, keys))
    assert shifts != [date_shift_days(k) for k in keys]  # single offsets may repeat by chance


def test_pseudonym_book_refuses_a_rotated_secret(monkeypatch):
    book = PseudonymBook()
    book.get("patient")
    monkeypatch.setenv("RAKSHA_SECRET", "rotated-secret")
    with pytest.raises(RuntimeError, match="secret_changed"):
        book.get("patient")


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_secret_is_an_error(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RAKSHA_SECRET")
    else:
        monkeypatch.setenv("RAKSHA_SECRET", value)
    with pytest.raises(RuntimeError, match="RAKSHA_SECRET"):
        PseudonymBook()


# --------------------------------------------------------------------------- decisions and dates
def test_decide_for_linked_and_unlinked_records():
    book = PseudonymBook()
    first, second = decide("k1", rec("a"), book), decide("k1", rec("b"), book)
    assert first.patient_id == second.patient_id == book.get("k1")
    assert first.shift_days == second.shift_days != 0
    unlinked = decide(None, rec("c"), book)
    assert unlinked.patient_id is None
    assert unlinked.shift_days == decide(None, rec("c"), book).shift_days
    assert not unlinked.suppress and decide(None, rec("c"), book, suppress=True).suppress


def test_date_shift_is_bounded_nonzero_and_keeps_stay_length():
    admitted, discharged = dt.date(2026, 2, 10), dt.date(2026, 2, 20)
    for i in range(200):
        key = f"patient-{i}"
        assert 0 < abs(date_shift_days(key)) <= 180
        assert shift_date(discharged, key) - shift_date(admitted, key) == discharged - admitted


@pytest.mark.parametrize("age", [0, 4, 5, 47, 99])
def test_age_band_contains_true_age(age):
    low, high = map(int, age_band(age).split("-"))
    assert low <= age <= high


# --------------------------------------------------------------------------- rare combinations
def _group(count, key=lambda i: f"p{i}"):
    return [(key(i), rec(i, age=47, sex="F", locations=["Rampur"])) for i in range(count)]


def test_rare_refs_flags_small_groups_only():
    assert rare_refs(_group(5)) == set()
    small = _group(4)
    assert rare_refs(small) == {c.ref for _, c in small}


def test_rare_refs_counts_patients_not_records():
    one_patient = _group(6, key=lambda i: "same")
    unlinked = _group(6, key=lambda i: None)
    assert len(rare_refs(one_patient)) == 6
    assert len(rare_refs(unlinked)) == 6
