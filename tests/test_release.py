import json

import pytest

from main import main
from wards.release import Stats, choose_rel, reason_of, safe_rel, write_release, write_sanitized


def test_safe_rel_cleans_paths_and_resolves_case_insensitive_collisions():
    taken = set()
    assert safe_rel(r"../Ward\a?.csv", taken) == "Ward/a_.csv"
    assert safe_rel("ward/A_.csv", taken) == "ward/A__2.csv"
    assert safe_rel("../.", taken) == "file"


@pytest.mark.parametrize(("new_name", "expected"), [
    (None, "ward/source.csv"),
    ("clean.csv", "ward/clean.csv"),
    ("export/clean.csv", "export/clean.csv"),
])
def test_choose_rel(new_name, expected):
    assert choose_rel("ward/source.csv", new_name) == expected


def test_write_sanitized_preserves_utf8_and_line_endings(tmp_path):
    text = "मात्रा,Dose\r\n5,650 mg\r\n"
    write_sanitized(tmp_path, "ward/table.csv", text)
    assert (tmp_path / "sanitized/ward/table.csv").read_bytes() == text.encode("utf-8")


def test_write_sanitized_rejects_escape(tmp_path):
    with pytest.raises(ValueError, match="^path_escape$"):
        write_sanitized(tmp_path, "../outside.txt", "sample")
    assert not (tmp_path / "outside.txt").exists()


def test_quarantine_reason_only_exposes_known_codes():
    assert reason_of(ValueError("empty_file")) == "empty_file"
    assert reason_of(ValueError("PrivateName")) == "ValueError"
    assert reason_of(KeyError("PrivateName")) == "KeyError"


def test_release_counts_and_exports_only_records_from_released_files(tmp_path):
    output = "sanitized/table.csv"
    files = [
        {"input_sha256": "a" * 64, "output": output, "status": "sanitized"},
        {"input_sha256": "b" * 64, "output": None, "status": "quarantined", "reason": "empty_file"},
    ]
    released = [
        {"file": output, "loc": "row:0", "patient": "PSN-001"},
        {"file": output, "loc": "row:1", "patient": None},
    ]
    skipped = {"file": "sanitized/empty.csv", "loc": "row:0", "patient": "PSN-002"}
    stats = Stats(identifiers_detected=3, records_generalized=2, records_suppressed=1)
    write_release(tmp_path, files, [*released, skipped], stats, seconds=1.234)

    lines = (tmp_path / "records.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == released
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["schema"] == "raksha-report/1"
    assert report["files"] == files
    assert report["timing"]["seconds"] == 1.23
    assert report["counts"] == {
        "files_total": 2, "files_sanitized": 1, "files_quarantined": 1,
        "records_processed": 2, "records_linked": 1, "identifiers_detected": 3,
        "records_generalized": 2, "records_suppressed": 1, "records_quarantined": 0,
    }


# --------------------------------------------------------------------------- whole pipeline
def _make_input(tmp_path):
    inp = tmp_path / "input"
    (inp / "ward").mkdir(parents=True)
    (inp / "ward" / "table.csv").write_text("UHID,Dose\nUHID-012345,650 mg\nUHID-054321,5 mg\n", encoding="utf-8")
    (inp / "ward" / "visits.json").write_text('{"visits":[{"patient_ref":"UHID-012345"}]}', encoding="utf-8")
    (inp / "note_9876543210.txt").write_text("Seen under UHID-012345.", encoding="utf-8")
    (inp / "broken.json").write_text('{"patient":', encoding="utf-8")
    (inp / "scan.pdf").write_bytes(b"%PDF-1.4 synthetic")
    return inp


def _run(inp, out):
    assert main(["--input", str(inp), "--output", str(out)]) == 0
    records = [json.loads(line) for line in (out / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    tree = {p.relative_to(out).as_posix(): p.read_bytes()
            for p in sorted((out / "sanitized").rglob("*")) if p.is_file()}
    return records, tree


def test_pipeline_locators_quarantine_and_renaming(tmp_path):
    out = tmp_path / "out"
    records, tree = _run(_make_input(tmp_path), out)
    assert sorted(r["loc"] for r in records) == ["/visits/0", "doc", "row:0", "row:1"]
    assert {r["file"] for r in records} == set(tree)
    assert not any("9876543210" in name or "broken" in name or "scan" in name for name in tree)
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["counts"]["files_total"] == 5
    assert report["counts"]["files_quarantined"] == 2


def test_pipeline_is_deterministic_and_keyed(tmp_path, monkeypatch):
    inp = _make_input(tmp_path)
    first = _run(inp, tmp_path / "one")
    assert first == _run(inp, tmp_path / "two")
    monkeypatch.setenv("RAKSHA_SECRET", "rotated-secret")
    assert first != _run(inp, tmp_path / "three")


def test_pipeline_without_secret_writes_nothing(tmp_path, monkeypatch):
    inp = _make_input(tmp_path)
    monkeypatch.delenv("RAKSHA_SECRET")
    with pytest.raises(RuntimeError, match="RAKSHA_SECRET"):
        main(["--input", str(inp), "--output", str(tmp_path / "out")])
    assert not (tmp_path / "out").exists()
