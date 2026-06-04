# Document & OCR Specifications (Enterprise Underwriting)

This document defines the strict requirements for applicant documents, the proposal form structure, and the expected OCR extraction JSON schema used by the intelligent underwriting assistant.

## 1. Applicant Document Requirements
The following documents are mandatory or conditionally requested during underwriting.

### A. KYC & Identity
1. **Aadhaar Card**
   - **Fields**: Name, DOB, Gender, Address, 12-digit Aadhaar Number.
   - **Underwriting Relevance**: Fraud prevention, exact age calculation (for age loading).
   - **Fraud-Sensitive**: Overwritten DOB, address mismatch with proposal form.
2. **PAN Card**
   - **Fields**: Name, Father's Name, DOB, 10-character PAN.
   - **Underwriting Relevance**: Financial underwriting (mandatory for policies > ₹50 Lakhs Sum Insured).

### B. Medical Reports (Mandatory for Tele-MER / Physical MER)
3. **Blood Test Report (Fasting & PP)**
   - **Fields**: Glucose Fasting (mg/dL), HbA1c (%), Lipid Profile (Total Cholesterol, Triglycerides, HDL, LDL).
   - **Underwriting Relevance**: Diabetes and cardiovascular risk assessment.
4. **ECG Report**
   - **Fields**: Heart Rate, PR Interval, QRS Duration, Impression (e.g., "Normal Sinus Rhythm" or "Left Ventricular Hypertrophy").
   - **Underwriting Relevance**: High-risk cardiac flags.

### C. Financial & Historical Documents
5. **Hospitalization Summary (Discharge Summary)**
   - **Fields**: Date of Admission (DOA), Date of Discharge (DOD), Primary Diagnosis, Surgical Procedures, Attending Physician.
   - **Underwriting Relevance**: Pre-Existing Disease (PED) waiting period mapping.
6. **Previous Insurance Policy / Claim History Report**
   - **Fields**: Previous Insurer Name, Claim Amount, ICD-10 Code, TPA Name, Claim Status (Settled/Repudiated).
   - **Underwriting Relevance**: Identification of chronic illness, porting eligibility.

---

## 2. Health Insurance Proposal Form Structure

*This schema mimics the real-world proposal forms of ICICI Lombard or SBI General.*

### Section A: Proposer Details
- **Full Name**: [String]
- **Date of Birth**: [DD/MM/YYYY]
- **Occupation**: [Dropdown: Salaried, Self-Employed Professional, Hazardous/Manual Labor]
- **Gross Annual Income**: [Numeric] (Determines financial eligibility limits, e.g., max Sum Insured = 10x Annual Income).

### Section B: Lifestyle Disclosures (Fraud-Prone Area)
- **Smoking Habits**: [Boolean] If Yes, Quantity per day: ___
- **Alcohol Consumption**: [Boolean] If Yes, ml per week: ___
- **Tobacco Usage (Chewing)**: [Boolean]

### Section C: Medical History (PED Declaration)
*Mandatory Insurer Validation: Any "Yes" requires a detailed uploaded report.*
- **Have you ever been diagnosed with Diabetes/Hypertension?** [Y/N]
- **Have you undergone any surgery in the last 48 months?** [Y/N]
- **Is there any family medical history of Heart Disease/Cancer before age 60?** [Y/N]

---

## 3. OCR Extraction Requirements & JSON Logic

The OCR engine (backed by PyMuPDF/Vision API) must output the following standardized JSON. The system includes fallback regex validations.

### A. Blood Test Extraction (HbA1c & Lipid)
```json
{
  "document_type": "Pathology_Report",
  "confidence_score": 0.94,
  "extracted_data": {
    "patient_name": "Rajesh Kumar",
    "test_date": "2026-05-10",
    "biomarkers": {
      "HbA1c": {
        "value": 7.8,
        "unit": "%",
        "reference_range": "4.0 - 5.6",
        "regex_match_used": true
      },
      "fasting_blood_sugar": {
        "value": 145,
        "unit": "mg/dL",
        "reference_range": "70 - 100"
      },
      "total_cholesterol": {
        "value": 240,
        "unit": "mg/dL",
        "reference_range": "< 200"
      }
    }
  },
  "validation_flags": {
    "name_mismatch_with_proposal": false,
    "abnormal_values_detected": ["HbA1c", "fasting_blood_sugar", "total_cholesterol"]
  }
}
```

### B. Discharge Summary Extraction
```json
{
  "document_type": "Discharge_Summary",
  "confidence_score": 0.88,
  "extracted_data": {
    "hospital_name": "Apollo Gleneagles Hospitals, Kolkata",
    "admission_date": "2024-11-12",
    "discharge_date": "2024-11-18",
    "primary_diagnosis": "Acute Appendicitis with Localized Peritonitis",
    "procedures_performed": ["Laparoscopic Appendectomy"],
    "medications_prescribed_on_discharge": ["Tab. Pan 40mg", "Tab. Augmentin 625mg"]
  },
  "low_confidence_handling": {
    "missing_fields": ["attending_physician_reg_no"],
    "action": "ROUTE_TO_MANUAL_REVIEW"
  }
}
```

### C. OCR Validation & Fallback Logic
1. **Low Confidence Handling**: If overall `confidence_score` < 0.70, the document status is set to `Intake Processing - Error` and routed to the manual Data Entry Maker.
2. **Regex Validations**:
   - HbA1c Regex: `r"(?i)HbA1c[\s\S]{0,20}?(\d{1,2}\.\d{1,2})"`
   - PAN Regex: `r"[A-Z]{5}[0-9]{4}[A-Z]{1}"`
3. **Missing Field Handling**: If a mandatory biomarker (like HbA1c in a diabetic case) is missing, the API auto-triggers the Clarification Workflow (`request_document`).
