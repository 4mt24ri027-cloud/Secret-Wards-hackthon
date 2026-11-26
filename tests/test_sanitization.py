import unittest

from main import process_csv
from wards.formats import read_rows


class HospitalIdentifierTests(unittest.TestCase):
    def test_linkage_sees_original_id_and_release_preserves_dose(self):
        for header in ("UHID", "MRN", "Medical Record Number", "Hospital Number"):
            with self.subTest(header=header):
                source = f"{header},Dose\n00123,650 mg\n"
                from main import file_clues
                clues = file_clues(source, ".csv", "sample.csv")
                self.assertTrue(clues[0].hospital_ids[0].endswith("00123"))
                result = process_csv(source, ",", "sample.csv", [])
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

class ContactPrivacyTests(unittest.TestCase):
    def test_release_channels(self):
        import base64
        from main import clean_text, clean_value

        self.assertEqual(clean_text("Ada North (attendant, bed 9)"), "[VISITOR_NAME] (attendant, bed 9)")
        self.assertTrue(clean_text("called by Arun West 98765-43210").startswith("called by [CONTACT_NAME] "))
        self.assertEqual(clean_value({"raised_by": {"name": "Mira East"}})["raised_by"]["name"], "[CONTACT_NAME]")
        data = base64.b64encode(b"Consent witnessed by Tara South, dose 5 mg.").decode()
        result = clean_value({"contentType": "text/plain", "data": data})
        self.assertEqual(base64.b64decode(result["data"]), b"Consent witnessed by [WITNESS_NAME], dose 5 mg.")

class NarrativeIdentifierTests(unittest.TestCase):
    def test_hospital_ids_with_clinical_numbers(self):
        from main import clean_text

        for identifier in ["UHID-093482", "SNJ/24/012345", "ipd-2025-01234", "JJH-1234567"]:
            note = f"Seen under {identifier}. BP 120/80, dose 650 mg."
            self.assertEqual(clean_text(note), "Seen under [MRN]. BP 120/80, dose 650 mg.")

class StructuredRegistrationTests(unittest.TestCase):
    def test_registration_and_fhir_names(self):
        from main import clean_value

        registration = {"patients": [{"name": {"local": "तारा", "last": "West"},
                                     "guardian": {"name": "Example Guardian"},
                                     "address": {"line": "House 7", "district": "Example District"}}]}
        patient = clean_value(registration)["patients"][0]
        self.assertEqual(set(patient["name"].values()), {"[PATIENT_NAME]"})
        self.assertEqual(patient["guardian"]["name"], "[RELATIVE_NAME]")
        self.assertEqual(patient["address"], {"line": "[ADDRESS]", "district": "Example District"})
        resource = {"resourceType": "Patient", "name": [{"given": ["Tara"], "use": "official"}]}
        self.assertEqual(clean_value(resource)["name"], [{"given": ["[PATIENT_NAME]"], "use": "official"}])

class RelativeLabelTests(unittest.TestCase):
    def test_relative_names_in_notes(self):
        from main import clean_text

        for label, name in [("S/o", "Aman Dev"), ("W/o", "Nila"), ("पिता का नाम:", "अजय निषाद")]:
            self.assertEqual(clean_text(f"{label} {name}, BP 120/80"),
                             f"{label} [RELATIVE_NAME], BP 120/80")

    def test_clinical_complaints(self):
        from main import clean_text

        note = "C/O Fever. K/C/O diabetes. Dr. Example advised review."
        self.assertEqual(clean_text(note), note)

class LabResultPrivacyTests(unittest.TestCase):
    def test_patient_aliases_preserve_test_name_and_value(self):
        from main import clean_value

        for key in ("patient_name", "Patient Name"):
            result = {"results": [{key: "Example Person", "name": "Glucose", "value": "245 mg/dL"}]}
            self.assertEqual(clean_value(result)["results"][0], {
                key: "[PATIENT_NAME]", "name": "Glucose", "value": "245 mg/dL"
            })

class LabRemarkTests(unittest.TestCase):
    def test_attendant_phrase_preserves_clinical_text(self):
        from main import clean_text

        for name, apostrophe in [("Nila", "'"), ("Aman Dev", "’")]:
            suffix = f"{apostrophe}s attendant. Hb 11.2 g/dL."
            self.assertEqual(clean_text("Sample received from " + name + suffix),
                             "Sample received from [PATIENT_NAME]" + suffix)
        note = "Sample received from Central Lab. Hb 11.2 g/dL."
        self.assertEqual(clean_text(note), note)

class RegistrationHeaderTests(unittest.TestCase):
    def test_split_and_hinglish_names_require_registration_context(self):
        from wards.detect import classify_columns

        self.assertEqual(classify_columns(["Reg No", "Janm Tithi", "Naam"])[2], "PATIENT_NAME")
        self.assertEqual(classify_columns(["PatientID", "DOB (MM/DD/YYYY)", "FirstName", "LastName"])[2:],
                         ["PATIENT_NAME", "PATIENT_NAME"])
        self.assertEqual(classify_columns(["Department", "FirstName"]), [None, None])

class ExportMetadataTests(unittest.TestCase):
    def test_source_path_is_removed_without_changing_other_fields(self):
        from main import clean_value

        for path in [r"D:\exports\Example_Patient_001\report.json", "/exports/Example_Patient/report.json"]:
            report = {"_export_meta": {"source_path": path, "system": "OPD"},
                      "result": "245 mg/dL"}
            self.assertEqual(clean_value(report), {
                "_export_meta": {"source_path": "[SOURCE_PATH]", "system": "OPD"},
                "result": "245 mg/dL"
            })

class PatientDemographicsTests(unittest.TestCase):
    def test_fhir_birth_year_and_district_preserve_encounter_date(self):
        from main import clean_value

        patient = {"resourceType": "Patient", "birthDate": "1986-05-17",
                   "address": [{"city": "Example Village", "district": "Example District", "postalCode": "123456"}]}
        cleaned = clean_value(patient)
        self.assertEqual(cleaned["birthDate"], "1986")
        self.assertEqual(cleaned["address"][0], {"city": "Example District", "district": "Example District",
                                                "postalCode": "[POSTCODE]"})
        self.assertEqual(clean_value({"date": "2025-05-17"}), {"date": "2025-05-17"})

class DischargeDemographicsTests(unittest.TestCase):
    def test_english_and_hindi_labels_preserve_clinical_lines(self):
        from main import process_text

        for label in ["Address", "पता"]:
            note = f"{label}: Example Village - 123456\r\nDOB: 17/05/1986\r\nAdmission: 12/04/2025\nDose: 650 mg"
            expected = f"{label}: [ADDRESS]\r\nDOB: [DOB]\r\nAdmission: 12/04/2025\nDose: 650 mg"
            self.assertEqual(process_text(note, "sample.txt", []), expected)

class VillagePrivacyTests(unittest.TestCase):
    def test_prescription_and_registration_locality(self):
        from main import process_text

        note = "ग्राम: उदाहरण\nतारीख: 12/05/2025\nDose: 5 mg"
        self.assertEqual(process_text(note, "rx.txt", []), note.replace("उदाहरण", "[ADDRESS]"))
        result = process_csv("City,District,Dose\nExample Village,Example District,5 mg\n", ",", "r.csv", [])
        self.assertEqual(list(read_rows(result))[1], ["Example District", "Example District", "5 mg"])

class HindiPrescriptionTests(unittest.TestCase):
    def test_repeated_patient_name_preserves_age_symptoms_and_dose(self):
        from main import process_text

        note = "नाम: तारा देवी   आयु: 42 वर्ष\nतारा देवी को बुखार है।\nRx 100 mg\nDr. Example"
        self.assertEqual(process_text(note, "rx.txt", []), note.replace("तारा देवी", "[PATIENT_NAME]"))
