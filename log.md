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