import base64

from wards.formats import read_file, read_rows
from wards.sanitize import clean_value, sanitize_file


def clean(name, text, release_names=None):
    return sanitize_file(read_file(name, text.encode("utf-8")), {}, release_names).text


def test_fhir_names_are_removed_from_display_narrative_and_attachment():
    referral = base64.b64encode(b"Referral: Tara South, dose 5 mg.").decode()
    bundle = {"resourceType": "Bundle", "entry": [
        {"resource": {"resourceType": "Patient", "name": [{"text": "Tara South"}],
                      "contact": [{"name": {"text": "Arun South"}}]}},
        {"resource": {"resourceType": "Composition",
                      "subject": {"reference": "urn:uuid:1", "display": "Tara South"},
                      "text": {"div": "<div>Tara South, kin Arun South, Hb 9.9 g/dL</div>"},
                      "author": [{"display": "Dr. Tara South"}]}},
        {"resource": {"resourceType": "DocumentReference", "content": [
            {"attachment": {"contentType": "text/plain", "data": referral}}]}},
    ]}
    import json
    out = json.loads(clean("b.json", json.dumps(bundle)))
    composition = out["entry"][1]["resource"]
    assert composition["subject"] == {"reference": "urn:uuid:1", "display": "[PATIENT_NAME]"}
    assert composition["text"]["div"] == "<div>[PATIENT_NAME], kin [RELATIVE_NAME], Hb 9.9 g/dL</div>"
    assert composition["author"][0]["display"] == "Dr. Tara South"
    data = out["entry"][2]["resource"]["content"][0]["attachment"]["data"]
    assert base64.b64decode(data) == b"Referral: [PATIENT_NAME], dose 5 mg."


def test_release_wide_full_name_reaches_free_text_but_single_word_does_not():
    names = {"tara south": "[PATIENT_NAME]", "south": "[PATIENT_NAME]"}
    assert clean("n.txt", "Tara South seen. South wing.", names) == "[PATIENT_NAME] seen. South wing."


def test_redacted_keys_never_overwrite_each_other():
    out = clean_value({"JJH-0000001": 1, "JJH-0000002": 2})
    assert sorted(out.values()) == [1, 2]


def test_honorific_rules_keep_doctor_and_dose():
    text = "Asha ji: Dolo 650 BD. Dr. Ramesh ji ne bola. Mohan Papa"
    assert clean("n.txt", text) == (
        "[PATIENT_NAME] ji: Dolo 650 BD. Dr. Ramesh ji ne bola. [RELATIVE_NAME] Papa")


def test_devanagari_phone_insurance_and_headers():
    assert clean("n.txt", "मोबाइल: ८९२१६७८५४१") == "मोबाइल: [PHONE]"
    table = clean("r.csv", "JJH-0000001 Tara,policy_no\r\n5 mg,POL/1/23\r\n")
    assert list(read_rows(table)) == [["[MRN] [PATIENT_NAME]", "policy_no"], ["5 mg", "[INSURANCE_ID]"]]


def test_address_fragments_in_free_text():
    assert clean("n.txt", "H.No. 12, Mohalla Nai Basti, Ward: 4 (Medicine)") == (
        "[HOUSE], [LOCALITY], Ward: 4 (Medicine)")
