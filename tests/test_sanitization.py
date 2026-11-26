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
