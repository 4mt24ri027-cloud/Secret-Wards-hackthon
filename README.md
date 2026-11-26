# Secret Wards

**Team Never Give Up · Anish R and Prajnesh · Yugaantar DevForge, Track 3**

Secret Wards helps hospitals prepare records for research. A researcher may need to know that someone received a medicine twice, nine days apart. The person's name, phone number and home address could give away who they are. Our program makes a cleaned copy of the records so researchers can study the treatment while fewer personal details travel with it.

## How it works

```text
Hospital files → Find personal details → Match visits → Clean the records
                                                              ↓
                               Cleaned files + list of matches + report
```

1. **Read the files.** The program opens tables, hospital data files (JSON and FHIR) and written notes. It looks for names in English, Hindi and Hinglish, including in file names and supported text attachments. If a form names a patient and a doctor mentions that person later in a note, the program can use the form to find the repeated name.
2. **Match visits before removing names.** A hospital number or several details that agree can help connect two records. Two people may share a name or phone. If the evidence is weak, the program can leave the records separate.
3. **Give each matched patient a code.** A secret key helps generate a code that stands in for the patient's name. The same patient gets the same code within a release. Changing the secret changes the codes. The program can move a patient's dates together so a nine-day gap stays nine days. It can also replace an exact age with an age range and remove a district when too few patients share the same details.
4. **Write the results.** The folder `sanitized/` holds the cleaned files. The file `records.jsonl` lists the patient code for each record when a match is available. The file `report.json` counts what was processed and explains why a file was set aside. The original files stay in place.

## What happened in practice

The organizers supplied 200 files with made-up patient records. Secret Wards released 195 and set aside five. The checker found **0 of the 3,230 known personal details** and **0 of four planted test identities** in the release. It found **4,763 of the 4,855 details marked useful for research (98.1%)**. All 92 omitted details were district names, so researchers lose some ability to compare places.

The program assigned codes to 719 of 823 records. On the practice check, its matches had precision 1.00 and recall 0.74. In plain language, the checker reported no incorrect patient merges, but the program missed about a quarter of the expected links. Its combined matching score (F0.5) was 0.94.

## What still needs care

Someone who already knows a patient's age range, sex and district may still recognize them. In one table of 27 linked patients, two people were each alone in their group when we compared those three details. Unfamiliar names, dates and file layouts can also cause mistakes. The official score on unseen records is unknown.

Secret Wards runs offline on an ordinary computer using Python. It uses no trained models. Working notes about patient identities stay in memory, and the program prints counts. Whoever runs it must protect the original files and the computer's temporary memory storage with disk encryption, keep the keys separately and limit who can open the cleaned files.

## How to try it

Install Python 3.10 or later and place the organizers' `Secret-Wards-ToolKit` folder beside this repository. Open PowerShell in this repository and run the following commands. Use a new, empty output folder each time. The word `practice` is a public key for this example. The judges supply a private key for their run.

```powershell
python -m pip install -r requirements.txt
$env:RAKSHA_SECRET = "practice"
python main.py --input ../Secret-Wards-ToolKit/dev/input --output out
python ../Secret-Wards-ToolKit/validate_output.py --input ../Secret-Wards-ToolKit/dev/input --output out
python ../Secret-Wards-ToolKit/check_dev.py --output out
python ../Secret-Wards-ToolKit/check_submission.py --repo . --run
```

The first checker verifies the file format, the second measures practice results and the last checks submission readiness. On Linux use `export RAKSHA_SECRET=practice` to set the key. On Windows keep the toolkit's original line endings so the checker can recognize renamed files. Developers can install pytest and run `python -m pytest -q`. The judges use `raksha.toml` to start the program; privacy settings are in `config/policy.yaml`.
