import json

import pytest

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
