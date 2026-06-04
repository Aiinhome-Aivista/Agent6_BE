# Enterprise Underwriting Test Datasets & Scenarios

These 6 applicant scenarios represent real-world Indian underwriting test cases, including the simulated OCR output, rules triggered, and the final automated decision.

---

## Scenario 1: Low Risk (STP Auto-Approve)
- **Applicant**: Rahul Sharma, Age 28
- **Product**: Standard Plan
- **Disclosures**: Non-smoker, no medical history.
- **Simulated OCR Data**: Blood test shows HbA1c 5.2%, BP 115/75.
- **Rules Triggered**: None.
- **Risk Score**: `0`
- **Final Decision**: **Auto Approve** (STP). No premium loading.

---

## Scenario 2: Medium Risk (Standard Loading)
- **Applicant**: Priya Patel, Age 42
- **Product**: Platinum Plan
- **Disclosures**: Non-smoker. Declared mild hypertension.
- **Simulated OCR Data**: Prescription uploaded shows Telmisartan 40mg. BP logged at 135/88.
- **Rules Triggered**:
  - `Hypertension_Stage_1`: Triggers +20 Risk Score.
- **Risk Score**: `20`
- **Premium Loading Applied**: 10% on base premium.
- **Final Decision**: **Review / Accept with Loading**.

---

## Scenario 3: High Risk (Senior Escalation)
- **Applicant**: Anil Deshmukh, Age 55
- **Product**: Gold Plan
- **Disclosures**: Smoker (10/day), Diabetic.
- **Simulated OCR Data**: HbA1c report shows 8.2%.
- **Rules Triggered**:
  - `Smoker_High_Freq`: +25 Score.
  - `Diabetes_Poor_Control` (HbA1c > 8.0 on Gold Plan): +50 Score.
- **Risk Score**: `75`
- **Final Decision**: **Escalate to Senior Underwriter**. 
- **Clarification Action**: Request TMT and 2D Echo.

---

## Scenario 4: Fraudulent Applicant (Graph Trigger)
- **Applicant**: "Suresh Kumar", Age 35
- **Product**: Family Floater
- **Disclosures**: Healthy, no claims.
- **Simulated OCR Data**: Uploaded a standard health checkup bill from *City Care Hospital*.
- **Rules Triggered**:
  - `Graph_Fraud_Match`: *City Care Hospital* is linked to 5 previous repudiated claims in ArangoDB (Fraud Ring detected).
- **Risk Score**: `100`
- **Final Decision**: **Referred to Investigation**. STP halted immediately.

---

## Scenario 5: Senior Citizen (Co-Pay Assignment)
- **Applicant**: Meera Devi, Age 68
- **Product**: Senior Citizen Plan
- **Disclosures**: Operated for Cataract in 2021.
- **Simulated OCR Data**: Discharge summary verifies routine cataract, no complications.
- **Rules Triggered**:
  - `Age_>_60`: Assigns mandatory 20% Co-Payment rule.
  - `Surgery_>_2_Years_Clear`: 0 Risk.
- **Risk Score**: `10`
- **Final Decision**: **Approved with 20% Co-Pay & Standard Waiting Periods**.

---

## Scenario 6: PED Declaration (Pre-Existing Disease)
- **Applicant**: Vikash Gupta, Age 45
- **Product**: Standard Plan
- **Disclosures**: Asthma diagnosed 5 years ago.
- **Simulated OCR Data**: Doctor's prescription shows daily inhaler use (Budesonide). No recent hospitalizations.
- **Rules Triggered**:
  - `Asthma_Controlled`: +15 Score.
  - `PED_Declaration_True`: Assigns 48-month waiting period specifically for Respiratory Illnesses.
- **Risk Score**: `15`
- **Final Decision**: **Approved with 48-Month PED Exclusion**.
