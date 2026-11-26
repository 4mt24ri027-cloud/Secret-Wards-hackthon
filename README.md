# Secret Wards

Team **Never Give Up** · Anish R and Prajnesh · Yugaantar DevForge Track 3

This offline Python pipeline turns multilingual synthetic hospital exports into a research release. It uses names declared in structured records to find repeated mentions in clinical text, resolves records across hospitals, and applies release-specific pseudonyms and date shifts. It uses the Python standard library, CPU only. There are no trained models or runtime downloads.

## Running the submission

Use Python 3.10 or later. Run setup once with `python -m pip install -r requirements.txt`. The evaluator reads the setup and run commands from `raksha.toml`. Provide a fresh empty output directory outside the input tree. On PowerShell, this example uses the public practice key. The evaluator supplies its own private key.

```powershell
$env:RAKSHA_SECRET = "practice"
python main.py --input ../Secret-Wards-ToolKit/dev/input --output out
python ../Secret-Wards-ToolKit/validate_output.py --input ../Secret-Wards-ToolKit/dev/input --output out
python ../Secret-Wards-ToolKit/check_dev.py --output out
python ../Secret-Wards-ToolKit/check_submission.py --repo . --run
```

On Linux, set the variable with `export RAKSHA_SECRET=practice`. For development tests install pytest and run `python -m pytest -q`. Keep practice truth and the toolkit outside the submission. On Windows use a toolkit checkout that preserves Git line endings so the input byte hashes agree with the answer key.

## Architecture

```text
CSV / TSV / JSON / FHIR / notes
              |
      decode and identify records
              |
      collect identity clues and declared names
              |
      cluster records and assign privacy decisions
              |
      redact, shift, generalize and serialize
              |
      sanitized/ + records.jsonl + report.json
```

The reader handles UTF-8, BOM-marked UTF-16 and legacy cp1252 exports. Detection uses column aliases, JSON context, Latin and Devanagari names, and Hinglish relationship and honorific patterns. Dates and numbers are interpreted in context to protect clinical measurements. The sanitizer also checks export paths, headers, keys, FHIR narratives and supported text attachments.

Linkage gathers evidence before redaction. Government identifiers, hospital identifiers and corroborated names or contact details produce candidate matches. Conflicts in demographics and government identifiers constrain merges. Ambiguous records can remain unlinked. The privacy layer derives keyed pseudonyms, applies consistent date offsets to supported dates, converts ages to bands and coarsens geography. Rare observed combinations trigger wider bands and additional suppression. Policy settings live in `config/policy.yaml`.

## Security and deployment

Supply the release secret through the environment from a secret manager. Restrict access to the process, input, release, swap and crash dumps. Deploy the read-only raw input and any swap on encrypted storage with volume keys managed separately. Volume encryption is an operator control. The executable reads the supplied input and keeps raw clues, linkage state and the name index in memory. It writes no raw intermediate database. Quarantine records a reason code and input digest without copying unprocessed payloads. Console output contains aggregate counts. Treat the resulting pseudonymized release as sensitive.

## Evidence and limitations

On the 200-file organizer practice set the checker found 0 of 3,230 personal-data items and 0 of 4 canaries in the release. It preserved 4,763 of 4,855 utility items (98.1%). The 92 missing items were district names. Linkage scored precision 1.00, recall 0.74 and F0.5 0.94. The run exported 195 files, quarantined five and assigned pseudonyms to 719 of 823 records. A separate two-row synthetic fixture with a new name and an alternate header preserved both doses, one patient pseudonym and the nine-day interval across shifted dates.

Zero detected practice leaks do not establish anonymity. A released registration table still had two singleton groups across nine age-band, sex and district combinations for 27 linked patients. The official attacks may use additional attributes. Unfamiliar name forms, nested schemas, unsupported encodings and ambiguous dates remain risks. Hidden-set scores and operator storage encryption require independent verification.
