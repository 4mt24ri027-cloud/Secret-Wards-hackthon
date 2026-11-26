from wards.contracts import Clues, RecordRef
from wards.linkage import link


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
    import json
    from main import collect_ids, process_csv, process_json, process_text

    csv = "UHID,Dose\nUHID-012345,650 mg\n"
    visit = '{"visits":[{"patient_ref":"UHID-012345"}]}'
    note = "Seen under UHID-012345."
    for name, text in [("a.csv", csv), ("b.json", visit), ("c.txt", note)]:
        (tmp_path / name).write_text(text, encoding="utf8")
    ids = collect_ids(sorted(tmp_path.iterdir()), tmp_path)
    records = []
    table = process_csv(csv, ",", "a.csv", records, ids)
    obj = json.loads(process_json(visit, "b.json", records, ids))
    document = process_text(note, "c.txt", records, ids)
    pid = records[0]["patient"]
    assert pid.startswith("PSN-")
    assert all(record["patient"] == pid for record in records)
    assert pid in table and obj["visits"][0]["patient_pseudonym"] == pid and pid in document
