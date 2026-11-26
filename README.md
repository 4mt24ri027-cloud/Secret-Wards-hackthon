# Never Give Up: Hide patient identities and keep visits connected

**Track 3 · Secret Wards** · Members: Anish R and Prajnesh · Repo: [Secret-Wards-hackthon](https://github.com/4mt24ri027-cloud/Secret-Wards-hackthon)

## 1. In one paragraph

A registration sheet and a discharge note can both reveal who a patient is. Secret Wards is a local Python tool that reads the files together before cleaning them. A full name learned from a registration sheet helps it find that name in a note. When two records can be linked, both get the same substitute ID, so a researcher can still follow the patient's visits.

## 2. Architecture

```text
Input files → Ingestion → Detection → Linking → Privacy layer
                                                    │
                       ┌────────────────────────────┼─────────────────┐
                       ▼                            ▼                 ▼
                   sanitized/                  report.json       records.jsonl
                   Cleaned files               Run summary       Record index
```

## 3. How it works

- **Ingestion:** Reads CSV, TSV, plain text and JSON, including FHIR health records. It handles UTF-8, marked UTF-16 and Windows-1252 text. If a file cannot be read or parsed, the report records why it was skipped.
- **Detection:** English and Hindi field labels, text patterns and names found in the input guide the search. Rules recognize Hindi name labels and Hinglish terms such as *ji*. Context matters: “S/o” can introduce a relative, while “C/O fever” describes a complaint.
- **Linkage & pseudonyms:** Shared IDs or similar-sounding names narrow the search. The tool compares Hindi and Latin spellings and looks for supporting clues such as a birth date. Conflicting birth dates block a match. Linked records get a substitute ID made with a secret key and HMAC-SHA256.
- **Privacy layer:** Linked visits share a date shift of up to 365 days. Ages use five-year bands, with 85+ for older patients. Rare combinations of age band, sex and location trigger wider bands and can hide the district in tables.
- **Security:** The key comes from the RAKSHA_SECRET environment variable. Linkage clues stay in memory. Console output shows counts. Quarantined files get a fingerprint and reason in the report. Encryption at rest depends on the host's storage settings.

## 4. USP

- A name found in one file can protect the same person elsewhere, even inside a JSON key or an encoded plain-text referral.
- A researcher can still measure time between visits. If admission and discharge were nine days apart, the shifted dates are also nine days apart.

## 5. Privacy–utility trade-off (measured on the practice data)

| Measure | Value |
|---|---|
| Personal data leaked | 0 of 3,230 overall. Latin, Devanagari (Hindi) and Hinglish each had 0.0% visible. |
| Medical values kept | 98.1% (4,763 of 4,855) |
| Linking precision / recall / F0.5 | 1.00 / 0.74 / 0.94 |
| Re-identification risk (estimate) | 19 of 19 linked FHIR patients were unique by age band (from 2026 minus birth year), district, shifted admission week and first diagnosis code. This measures uniqueness within that sample. |
| Run time / peak memory | 1.14 seconds / 36.0 MiB on one local run with 200 files |
| On data we did not tune on | With renamed columns, a new name and dates like 02-Sep-2025, both visits shared one ID, both doses survived and the 13-day gap stayed exact. |

The matching rules favor caution. The checker found no wrong merges, but the tool recovered only 74% of the expected links. Wider age bands and hidden districts make rare patients harder to single out and leave less detail for local studies. The FHIR sample shows why even a release with zero detected names can still expose a distinctive visit.

## 6. Known limitations

An unfamiliar name or phrase can escape the rules. A date containing only a year and month is left as written. Someone who already knows a patient's visit pattern may still recognize it after the dates move. The next step is to test new hospitals' note layouts and measure how often those patterns single out a patient.
