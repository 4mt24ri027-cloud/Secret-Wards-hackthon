import unittest

from wards.detect import collect_clues
from wards.formats import read_file, read_rows
from wards.sanitize import sanitize_file


def clean_file(rel, source):
    return sanitize_file(read_file(rel, source.encode("utf-8")), {}).text


class HospitalIdentifierTests(unittest.TestCase):
    def test_linkage_sees_original_id_and_release_preserves_dose(self):
        for header in ("UHID", "MRN", "Medical Record Number", "Hospital Number"):
            with self.subTest(header=header):
                source = f"{header},Dose\n00123,650 mg\n"
                clues = collect_clues(read_file("sample.csv", source.encode()))
                self.assertTrue(clues[0].hospital_ids[0].endswith("00123"))
                result = clean_file("sample.csv", source)
                self.assertEqual(list(read_rows(result)), [[header, "Dose"], ["[MRN]", "650 mg"]])

    def test_identity_columns_redact_partial_values_and_keep_clinical_cells(self):
        for delimiter in (",", "\t"):
            with self.subTest(delimiter=delimiter):
                headers = ["Aadhaar No", "ABHA No", "Dose", "Lab"]
                values = ["xxxx-1234", "12-3456-7890-1234", "650 mg", "245 mg/dL"]
                source = delimiter.join(headers) + "\n" + delimiter.join(values)
                result = clean_file("sample.csv" if delimiter == "," else "sample.tsv", source)
                self.assertEqual(list(read_rows(result, delimiter)), [
                    headers, ["[AADHAAR]", "[ABHA_NUMBER]", "650 mg", "245 mg/dL"]
                ])

    def test_quoted_home_address_is_redacted_as_one_cell(self):
        source = 'Address,Dose\n"House 5, Example Road, Ward 2",650 mg\n'
        result = clean_file("sample.csv", source)
        self.assertEqual(list(read_rows(result)), [
            ["Address", "Dose"], ["[ADDRESS]", "650 mg"]
        ])

class JsonPatientNameTests(unittest.TestCase):
    def test_only_patient_name_is_redacted(self):
        import json

        report = {
            "patient": {"name": "Example Patient"},
            "referred_by": "Dr. Example",
            "panels": [{"name": "Glucose", "result": "245 mg/dL"}],
        }
        cleaned = json.loads(clean_file("lab/example.json", json.dumps(report)))
        self.assertEqual(cleaned, {**report, "patient": {"name": "[PATIENT_NAME]"}})

    def test_visit_reference_redacted_and_clinical_values_preserved(self):
        import json

        visit = {"patient_ref": "HOSP-01234", "visit_id": "visit-1", "bp": "120/80"}
        source = json.dumps({"visits": [visit]})
        cleaned = json.loads(clean_file("opd/example.json", source))
        self.assertEqual(cleaned["visits"], [{**visit, "patient_ref": "[PATIENT_REF]"}])

class HinglishNoteTests(unittest.TestCase):
    def test_names_before_honorific_and_bp(self):
        from wards.sanitize import clean_text

        for name, title in [("Nila", "behenji"), ("Mira", "bhenji"), ("Tara", "amma"), ("Aman Dev", "bhai")]:
            suffix = f" {title} ka BP 112/78, review in 2 weeks."
            self.assertEqual(clean_text(name + suffix), "[PATIENT_NAME]" + suffix)

    def test_clinical_and_clinician_text(self):
        from wards.sanitize import clean_text

        for note in ["bhenji ka BP 112/78", "Patient ka BP 112/78", "Dr. Aman bhai ka BP 120/80", "Dolo 650 mg"]:
            self.assertEqual(clean_text(note), note)

class ContactPrivacyTests(unittest.TestCase):
    def test_release_channels(self):
        import base64
        from wards.sanitize import clean_text, clean_value

        self.assertEqual(clean_text("Ada North (attendant, bed 9)"), "[VISITOR_NAME] (attendant, bed 9)")
        self.assertTrue(clean_text("called by Arun West 98765-43210").startswith("called by [CONTACT_NAME] "))
        self.assertEqual(clean_value({"raised_by": {"name": "Mira East"}})["raised_by"]["name"], "[CONTACT_NAME]")
        data = base64.b64encode(b"Consent witnessed by Tara South, dose 5 mg.").decode()
        result = clean_value({"contentType": "text/plain", "data": data})
        self.assertEqual(base64.b64decode(result["data"]), b"Consent witnessed by [WITNESS_NAME], dose 5 mg.")

class NarrativeIdentifierTests(unittest.TestCase):
    def test_hospital_ids_with_clinical_numbers(self):
        from wards.sanitize import clean_text

        for identifier in ["UHID-093482", "SNJ/24/012345", "ipd-2025-01234", "JJH-1234567"]:
            note = f"Seen under {identifier}. BP 120/80, dose 650 mg."
            self.assertEqual(clean_text(note), "Seen under [MRN]. BP 120/80, dose 650 mg.")

class StructuredRegistrationTests(unittest.TestCase):
    def test_registration_and_fhir_names(self):
        from wards.sanitize import clean_value

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
        from wards.sanitize import clean_text

        for label, name in [("S/o", "Aman Dev"), ("W/o", "Nila"), ("पिता का नाम:", "अजय निषाद")]:
            self.assertEqual(clean_text(f"{label} {name}, BP 120/80"),
                             f"{label} [RELATIVE_NAME], BP 120/80")

    def test_clinical_complaints(self):
        from wards.sanitize import clean_text

        note = "C/O Fever. K/C/O diabetes. Dr. Example advised review."
        self.assertEqual(clean_text(note), note)

class LabResultPrivacyTests(unittest.TestCase):
    def test_patient_aliases_preserve_test_name_and_value(self):
        from wards.sanitize import clean_value

        for key in ("patient_name", "Patient Name"):
            result = {"results": [{key: "Example Person", "name": "Glucose", "value": "245 mg/dL"}]}
            self.assertEqual(clean_value(result)["results"][0], {
                key: "[PATIENT_NAME]", "name": "Glucose", "value": "245 mg/dL"
            })

class LabRemarkTests(unittest.TestCase):
    def test_attendant_phrase_preserves_clinical_text(self):
        from wards.sanitize import clean_text

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
        from wards.sanitize import clean_value

        for path in [r"D:\exports\Example_Patient_001\report.json", "/exports/Example_Patient/report.json"]:
            report = {"_export_meta": {"source_path": path, "system": "OPD"},
                      "result": "245 mg/dL"}
            self.assertEqual(clean_value(report), {
                "_export_meta": {"source_path": "[SOURCE_PATH]", "system": "OPD"},
                "result": "245 mg/dL"
            })

class PatientDemographicsTests(unittest.TestCase):
    def test_fhir_birth_year_and_district_preserve_encounter_date(self):
        from wards.sanitize import clean_value

        patient = {"resourceType": "Patient", "birthDate": "1986-05-17",
                   "address": [{"city": "Example Village", "district": "Example District", "postalCode": "123456"}]}
        cleaned = clean_value(patient)
        self.assertEqual(cleaned["birthDate"], "1986")
        self.assertEqual(cleaned["address"][0], {"city": "Example District", "district": "Example District",
                                                "postalCode": "[POSTCODE]"})
        self.assertEqual(clean_value({"date": "2025-05-17"}), {"date": "2025-05-17"})

class DischargeDemographicsTests(unittest.TestCase):
    def test_english_and_hindi_labels_preserve_clinical_lines(self):

        for label in ["Address", "पता"]:
            note = f"{label}: Example Village - 123456\r\nDOB: 17/05/1986\r\nAdmission: 12/04/2025\nDose: 650 mg"
            expected = f"{label}: [ADDRESS]\r\nDOB: [DOB]\r\nAdmission: 12/04/2025\nDose: 650 mg"
            self.assertEqual(clean_file("sample.txt", note), expected)

class VillagePrivacyTests(unittest.TestCase):
    def test_prescription_and_registration_locality(self):

        note = "ग्राम: उदाहरण\nतारीख: 12/05/2025\nDose: 5 mg"
        self.assertEqual(clean_file("rx.txt", note), note.replace("उदाहरण", "[ADDRESS]"))
        result = clean_file("r.csv", "City,District,Dose\nExample Village,Example District,5 mg\n")
        self.assertEqual(list(read_rows(result))[1], ["Example District", "Example District", "5 mg"])

class HindiPrescriptionTests(unittest.TestCase):
    def test_repeated_patient_name_preserves_age_symptoms_and_dose(self):

        note = "नाम: तारा देवी   आयु: 42 वर्ष\nतारा देवी को बुखार है।\nRx 100 mg\nDr. Example"
        self.assertEqual(clean_file("rx.txt", note), note.replace("तारा देवी", "[PATIENT_NAME]").replace("42 वर्ष", "40-44 वर्ष"))

class VisitSubjectTests(unittest.TestCase):
    def test_bp_subject_without_honorific(self):
        from wards.sanitize import clean_value

        for subject, expected in [("Nila", "[PATIENT_NAME]"), ("Patient", "Patient"), ("Mother", "Mother")]:
            suffix = " ka BP 112/78, review after 2 weeks."
            visits = {"visits": [{"notes": subject + suffix}]}
            self.assertEqual(clean_value(visits)["visits"][0]["notes"], expected + suffix)

class DischargeNameTests(unittest.TestCase):
    def test_patient_roles_preserve_clinical_phrases(self):

        for original, expected in [
            ("मरीज़ का नाम: तारा देवी    आयु: 42", "मरीज़ का नाम: [PATIENT_NAME]    आयु: 40-44"),
            ("Hb 9.9 g/dL. Tara amma ki condition ab stable hai.",
             "Hb 9.9 g/dL. [PATIENT_NAME] amma ki condition ab stable hai."),
            ("Tara, W/o Arun, discharged.", "[PATIENT_NAME], W/o [RELATIVE_NAME], discharged."),
        ]:
            self.assertEqual(clean_file("summary.txt", original), expected)


class FhirMentionTests(unittest.TestCase):
    def test_display_narrative_and_referral_preserve_reference_and_dose(self):
        import base64
        import xml.etree.ElementTree as ET
        from wards.sanitize import redact_bundle_mentions

        obs = {"subject": {"display": "Tara West", "reference": "Patient/p1"},
               "text": {"div": '<div xmlns="http://www.w3.org/1999/xhtml">Tara West, 5 mg</div>'},
               "attachment": {"contentType": "text/plain", "data": base64.b64encode(b"Tara West, 5 mg").decode()}}
        patient = {"resourceType": "Patient", "name": [{"given": ["Tara"], "family": "West"}]}
        redact_bundle_mentions({"entry": [{"resource": patient}, {"resource": obs}]})
        self.assertEqual(obs["subject"], {"display": "[PATIENT_NAME]", "reference": "Patient/p1"})
        self.assertEqual(ET.fromstring(obs["text"]["div"]).text, "[PATIENT_NAME], 5 mg")
        self.assertEqual(base64.b64decode(obs["attachment"]["data"]), b"[PATIENT_NAME], 5 mg")


def test_unseen_registration_labels_and_opaque_column():
    header = "BeneficiaryFullName,Guardian display name,Age at intake,Home village,District,Extra,Dose"
    source = header + "\nTara West,Aman West,43,Riverton,North,Mr. Milan East,5 mg\n"
    from wards.privacy import age_label
    row = list(read_rows(clean_file("new.csv", source)))[1]
    assert row == ["[PATIENT_NAME]", "[RELATIVE_NAME]", age_label(43, 1),
                   "North", "North", "[PATIENT_NAME]", "5 mg"]


def test_narrative_patient_cues():
    from wards.sanitize import clean_text
    assert clean_text("Pt. Tara West, seen by Dr. Mira East.") == "Pt. [PATIENT_NAME], seen by Dr. Mira East."
    assert clean_text("Patient: Mr. Kiran Vale, BP 120/80") == "Patient: Mr. [PATIENT_NAME], BP 120/80"


def test_opaque_column_content_and_json_demographics():
    import json
    from wards.privacy import age_label

    source = "Field1,Field2,Field3,Field4\nS/o Arun Vale,43 years old,Village: Elm,650 mg\n"
    assert list(read_rows(clean_file("new.csv", source)))[1] == [
        "[RELATIVE_NAME]", age_label(43), "[LOCALITY]", "650 mg"
    ]
    record = {"intakeAge": "43 yrs", "homeVillage": "Elm", "guardianFullName": "Arun Vale"}
    assert json.loads(clean_file("new.json", json.dumps(record))) == {
        "intakeAge": age_label(43), "homeVillage": "[LOCALITY]", "guardianFullName": "[RELATIVE_NAME]"
    }

def test_unfamiliar_files_keep_clinical_values_and_remove_identifiers():
    import json
    table = clean_file("new.csv", "Beneficiary caption,Callback digits,Result\nNeris Talven,98.765.00235,118 mg/dL\n")
    assert "Neris Talven" not in table and "98.765.00235" not in table and "118 mg/dL" in table
    visit = clean_file("visit.json", json.dumps({"appointment": {
        "recipient_label": "Orla Venn", "contact_line": "98.765.00236", "reading": "111/73"}}))
    assert "Orla Venn" not in visit and "98.765.00236" not in visit and "111/73" in visit
    note = clean_file("handover.txt", "Seen today was Dalen Miro. Call back at 98.765.00237. Dose 2.5 mg.")
    assert "Dalen Miro" not in note and "98.765.00237" not in note and "2.5 mg" in note
