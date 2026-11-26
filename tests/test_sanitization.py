import unittest
from unittest.mock import patch

from main import process_csv
from wards.formats import read_rows


class HospitalIdentifierTests(unittest.TestCase):
    def test_linkage_sees_original_id_and_release_preserves_dose(self):
        for header in ("UHID", "MRN", "Medical Record Number", "Hospital Number"):
            with self.subTest(header=header):
                source = f"{header},Dose\n00123,650 mg\n"
                with patch("main.link_records", return_value=None) as link:
                    result = process_csv(source, ",", "sample.csv", [])
                link.assert_called_once_with("00123,650 mg")
                self.assertEqual(list(read_rows(result)), [[header, "Dose"], ["[MRN]", "650 mg"]])

    def test_identity_columns_redact_partial_values_and_keep_clinical_cells(self):
        for delimiter in (",", "\t"):
            with self.subTest(delimiter=delimiter):
                headers = ["Aadhaar No", "ABHA No", "Dose", "Lab"]
                values = ["xxxx-1234", "12-3456-7890-1234", "650 mg", "245 mg/dL"]
                source = delimiter.join(headers) + "\n" + delimiter.join(values)
                result = process_csv(source, delimiter, "sample", [])
                self.assertEqual(list(read_rows(result, delimiter)), [
                    headers, ["[AADHAAR]", "[ABHA_NUMBER]", "650 mg", "245 mg/dL"]
                ])

    def test_quoted_home_address_is_redacted_as_one_cell(self):
        source = 'Address,Dose\n"House 5, Example Road, Ward 2",650 mg\n'
        result = process_csv(source, ",", "sample.csv", [])
        self.assertEqual(list(read_rows(result)), [
            ["Address", "Dose"], ["[ADDRESS]", "650 mg"]
        ])

class JsonPatientNameTests(unittest.TestCase):
    def test_only_patient_name_is_redacted(self):
        import json
        from main import process_json

        report = {
            "patient": {"name": "Example Patient"},
            "referred_by": "Dr. Example",
            "panels": [{"name": "Glucose", "result": "245 mg/dL"}],
        }
        cleaned = json.loads(process_json(json.dumps(report), "lab/example.json", []))
        self.assertEqual(cleaned, {**report, "patient": {"name": "[PATIENT_NAME]"}})

    def test_visit_reference_redacted_and_clinical_values_preserved(self):
        import json
        from main import process_json

        visit = {"patient_ref": "HOSP-01234", "visit_id": "visit-1", "bp": "120/80"}
        source = json.dumps({"visits": [visit]})
        cleaned = json.loads(process_json(source, "opd/example.json", []))
        self.assertEqual(cleaned["visits"], [{**visit, "patient_ref": "[PATIENT_REF]"}])

class HinglishNoteTests(unittest.TestCase):
    def test_names_before_honorific_and_bp(self):
        from main import clean_text

        for name, title in [("Nila", "behenji"), ("Mira", "bhenji"), ("Tara", "amma"), ("Aman Dev", "bhai")]:
            suffix = f" {title} ka BP 112/78, review in 2 weeks."
            self.assertEqual(clean_text(name + suffix), "[PATIENT_NAME]" + suffix)

    def test_clinical_and_clinician_text(self):
        from main import clean_text

        for note in ["bhenji ka BP 112/78", "Patient ka BP 112/78", "Dr. Aman bhai ka BP 120/80", "Dolo 650 mg"]:
            self.assertEqual(clean_text(note), note)
