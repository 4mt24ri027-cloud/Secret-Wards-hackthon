## Before Development self-check output

```text
SECRET WARDS practice self-check (rough guide, not the official score)

1) PERSONAL DATA: 2718 of 3230 pieces still visible (84.1% leaked; lower is better)
   PATIENT_NAME     leaked  911 / 962   94.7%
   MRN              leaked  817 / 850   96.1%
   RELATIVE_NAME    leaked  232 / 232  100.0%
   VILLAGE          leaked  150 / 150  100.0%
   PIN              leaked  136 / 136  100.0%
   HOUSE            leaked  136 / 136  100.0%
   DOB              leaked  111 / 111  100.0%
   LOCALITY         leaked  103 / 103  100.0%
   LANDMARK         leaked   64 / 64   100.0%
   PHONE            leaked   25 / 308    8.1%
   AADHAAR_MASKED   leaked   16 / 16   100.0%
   INSURANCE_ID     leaked   15 / 22    68.2%
   AADHAAR          leaked    2 / 71     2.8%
   ABHA_NUMBER      leaked    0 / 46     0.0%
   PAN              leaked    0 / 22     0.0%
   EMAIL            leaked    0 / 1      0.0%

   by language: latin 82.8%, deva 100.0%, hinglish 100.0%
   by hiding place: content 83.5%, filename 100.0%, base64 100.0%,
                    metadata 100.0%, key 100.0%, header 100.0%

2) CANARIES: 4 of 4 planted canaries found in your output folder
   (each one costs -3 officially)

3) MEDICAL DATA KEPT: 4855 of 4855 medical values survived (100.0%; higher is better)

4) PATIENT LINKING: precision 0.00, recall 0.00, F0.5 0.00
   (pseudonyms that wrongly merge different people: 0)
   you linked nothing yet: write your pseudonym into records.jsonl "patient"

5) RAW COPIES: 0 broken/unsupported files were copied out unchanged
   instead of quarantined (each costs -5 officially)

Example leaks (type, language, place, file, text):
    DOB | latin | content | registration/sanjeevani_registration.csv | 12/04/1977
    RELATIVE_NAME | latin | content | registration/sanjeevani_registration.csv | Naresh Chauhan
    HOUSE | latin | content | registration/sanjeevani_registration.csv | H.No. 364
    LOCALITY | latin | content | registration/sanjeevani_registration.csv | Ward 20
    LOCALITY | latin | content | registration/sanjeevani_registration.csv | Mohalla Raja Bazar
    LANDMARK | latin | content | registration/sanjeevani_registration.csv | near Pani Tanki
    VILLAGE | latin | content | registration/sanjeevani_registration.csv | Durgamau Kalan
    PIN | latin | content | registration/sanjeevani_registration.csv | 229073
    MRN | latin | content | registration/sanjeevani_registration.csv | SNJ/26/064127
    PATIENT_NAME | latin | content | registration/sanjeevani_registration.csv | Mahesh Chauhan

Next: fix the biggest leak rows first, keep the medical values, then link patients.
```

At trail no :1
    
    ================================================================
     SECRET WARDS practice self-check (rough guide, not the official score)
    ================================================================
    
          1) PERSONAL DATA: 1080 of 3230 pieces still visible ( 33.4% leaked; lower is better)
             PATIENT_NAME     leaked  410 / 962   42.6%
             VILLAGE          leaked  150 / 150  100.0%
             PIN              leaked  136 / 136  100.0%
             DOB              leaked  111 / 111  100.0%
             MRN              leaked   64 / 850    7.5%
             HOUSE            leaked   62 / 136   45.6%
             RELATIVE_NAME    leaked   49 / 232   21.1%
             LOCALITY         leaked   42 / 103   40.8%
             LANDMARK         leaked   24 / 64    37.5%
             INSURANCE_ID     leaked   15 / 22    68.2%
             PHONE            leaked   15 / 308    4.9%
             AADHAAR          leaked    2 / 71     2.8%
             ABHA_NUMBER      leaked    0 / 46     0.0%
             PAN              leaked    0 / 22     0.0%
             AADHAAR_MASKED   leaked    0 / 16     0.0%
             EMAIL            leaked    0 / 1      0.0%
             by language: latin 30.4%, deva 86.0%, hinglish 46.8%
             by hiding place: content 31.1%, filename 100.0%, base64 90.0%, metadata 100.0%, key 50.0%, header 100.0%
    
          2) CANARIES: 0 of 4 planted canaries found in your output folder (each one costs -3 officially)
    
          3) MEDICAL DATA KEPT: 4855 of 4855 medical values survived (100.0%; higher is better)
    
          4) PATIENT LINKING: precision 1.00, recall 0.74, F0.5 0.94  (pseudonyms that wrongly merge different people: 0)
    
          5) RAW COPIES: 0 broken/unsupported files were copied out unchanged instead of quarantined (each costs -5 officially)
    
    Example leaks (type, language, place, file, text):
        DOB | latin | content | registration/sanjeevani_registration.csv | 12/04/1977
        VILLAGE | latin | content | registration/sanjeevani_registration.csv | Durgamau Kalan
        PIN | latin | content | registration/sanjeevani_registration.csv | 229073
        DOB | latin | content | registration/sanjeevani_registration.csv | 19/02/1976
        VILLAGE | latin | content | registration/sanjeevani_registration.csv | Shivmau Khurd
        PIN | latin | content | registration/sanjeevani_registration.csv | 225362
        DOB | latin | content | registration/sanjeevani_registration.csv | 10/11/1970
        VILLAGE | latin | content | registration/sanjeevani_registration.csv | Amardih
        PIN | latin | content | registration/sanjeevani_registration.csv | 209182
        DOB | latin | content | registration/sanjeevani_registration.csv | 08/05/1982
    
    Next: fix the biggest leak rows first, keep the medical values, then link patients.
    Also run: python3 validate_output.py --input dev/input --output my_output
    (.venv) prajnesh@prajnesh-ASUS-TUF-Gaming-A15-FA506NCQ-FA506NCQ:~/PycharmProjects/secret-word$ 


trial 2
        RAKSHA_SECRET=practice python main.py --input data/input --output my_output
    files 200 sanitized 195 quarantined 5 records 823
    (.venv) prajnesh@prajnesh-ASUS-TUF-Gaming-A15-FA506NCQ-FA506NCQ:~/PycharmProjects/secret-word$ KIT="$HOME/PycharmProjects/scalar_hackthon_clone/Secret-Wards"
    python "$KIT/validate_output.py" --input data/input --output my_output
    python "$KIT/check_dev.py" --output my_output --show 10
    CONTRACT OK
    ================================================================
     SECRET WARDS practice self-check (rough guide, not the official score)
    ================================================================
    
          1) PERSONAL DATA: 831 of 3230 pieces still visible ( 25.7% leaked; lower is better)
             PATIENT_NAME     leaked  181 / 962   18.8%
             VILLAGE          leaked  150 / 150  100.0%
             PIN              leaked  136 / 136  100.0%
             DOB              leaked  111 / 111  100.0%
             HOUSE            leaked   62 / 136   45.6%
             RELATIVE_NAME    leaked   49 / 232   21.1%
             MRN              leaked   44 / 850    5.2%
             LOCALITY         leaked   42 / 103   40.8%
             LANDMARK         leaked   24 / 64    37.5%
             PHONE            leaked   15 / 308    4.9%
             INSURANCE_ID     leaked   15 / 22    68.2%
             AADHAAR          leaked    2 / 71     2.8%
             ABHA_NUMBER      leaked    0 / 46     0.0%
             AADHAAR_MASKED   leaked    0 / 16     0.0%
             PAN              leaked    0 / 22     0.0%
             EMAIL            leaked    0 / 1      0.0%
             by language: latin 22.3%, deva 79.7%, hinglish 46.8%
             by hiding place: content 24.4%, filename 100.0%, base64 90.0%, metadata 0.0%, key 50.0%, header 100.0%
    
          2) CANARIES: 0 of 4 planted canaries found in your output folder (each one costs -3 officially)
    
          3) MEDICAL DATA KEPT: 4855 of 4855 medical values survived (100.0%; higher is better)
    
          4) PATIENT LINKING: precision 1.00, recall 0.74, F0.5 0.94  (pseudonyms that wrongly merge different people: 0)
    
          5) RAW COPIES: 0 broken/unsupported files were copied out unchanged instead of quarantined (each costs -5 officially)
    
    Example leaks (type, language, place, file, text):
        DOB | latin | content | registration/sanjeevani_registration.csv | 12/04/1977
        VILLAGE | latin | content | registration/sanjeevani_registration.csv | Durgamau Kalan
        PIN | latin | content | registration/sanjeevani_registration.csv | 229073
        DOB | latin | content | registration/sanjeevani_registration.csv | 19/02/1976
        VILLAGE | latin | content | registration/sanjeevani_registration.csv | Shivmau Khurd
        PIN | latin | content | registration/sanjeevani_registration.csv | 225362
        DOB | latin | content | registration/sanjeevani_registration.csv | 10/11/1970
        VILLAGE | latin | content | registration/sanjeevani_registration.csv | Amardih
        PIN | latin | content | registration/sanjeevani_registration.csv | 209182
        DOB | latin | content | registration/sanjeevani_registration.csv | 08/05/1982
    
    Next: fix the biggest leak rows first, keep the medical values, then link patients.
    Also run: python3 validate_output.py --input dev/input --output my_output