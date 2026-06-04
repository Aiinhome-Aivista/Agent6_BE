# Enterprise Medical Underwriting Rulebook & Risk Engine Logic

This document outlines the deterministic scoring and decision logic used by the automated Underwriting Risk Engine. It includes product-specific variations and premium loading calculations typical of the Indian Health Insurance market.

## 1. Product-Specific Underwriting Variations

### A. Gold Plan (Standard/Conservative)
- **Target Demographic**: Broad retail base.
- **Diabetes Rules**: 
  - HbA1c < 6.5: Accept at Standard Rates.
  - HbA1c 6.5 - 7.5: Accept with 10% Premium Loading.
  - HbA1c > 7.5: Decline / Refer to Senior Underwriter.
- **Hypertension Rules**: 
  - BP > 140/90: Refer for Medical Checkup.
- **PED Waiting Period**: 48 Months standard.

### B. Platinum Plan (HNI / Relaxed Tolerance)
- **Target Demographic**: High Net Worth Individuals (HNI), high premium.
- **Diabetes Rules**: 
  - HbA1c up to 8.0: Accept with 15% Premium Loading (No outright decline).
- **Claim Tolerance**: Allows up to 2 minor claims in the previous year (Gold allows 0).
- **PED Waiting Period**: 24 Months (Reduced).

### C. Senior Citizen Plan
- **Target Demographic**: Age 60+.
- **Co-Payment Logic**: Mandatory 20% Co-Payment on all claims.
- **Auto-Rejection Rules**: 
  - Age > 75 + History of Cardiac Surgery = Decline.

---

## 2. Underwriting Risk Engine (Scoring Logic)

The Risk Engine uses a deterministic scoring matrix where higher scores indicate higher risk.

### A. Medical Scoring Matrix
| Condition / Biomarker | Value Range | Risk Score Assigned | Rule Trigger |
| :--- | :--- | :--- | :--- |
| **BMI** | 18.5 - 24.9 | 0 | Normal |
| **BMI** | 30.0 - 34.9 | 15 | Obesity Loading (10%) |
| **BMI** | > 35.0 | 40 | High Risk - Refer |
| **HbA1c** | 5.7 - 6.4 (Prediabetic) | 10 | Standard Accept |
| **HbA1c** | 6.5 - 7.5 | 25 | Loading Trigger |
| **HbA1c** | > 8.0 | 50 | Auto Decline (Standard Plans) |
| **Blood Pressure** | > 140/90 | 20 | Hypertension Loading |

### B. Lifestyle & Claim Scoring Matrix
| Factor | Value | Risk Score Assigned | Rule Trigger |
| :--- | :--- | :--- | :--- |
| **Smoking Habits** | > 5 Cigarettes/day | 25 | Smoker Loading (15%) |
| **Alcohol Habits** | > 14 units/week | 20 | LFT Report Required |
| **Previous Claims** | 1 Claim in 3 Yrs | 10 | Review Diagnosis |
| **Previous Claims** | > 3 Claims in 3 Yrs | 60 | Escalation to Senior UW |

### C. Explainable Risk Score & Final Decision Logic

The Total Risk Score is the sum of Medical + Lifestyle + Claims + Fraud scores.

* **0 – 25 points**: **Auto Approve (STP - Straight Through Processing)**
  - Action: Issue Policy instantly. No manual intervention.
* **26 – 50 points**: **Review / Standard Loading**
  - Action: Auto-apply computed premium loading. Send to Underwriter for quick 1-click approval.
* **51 – 75 points**: **Senior Underwriter Escalation**
  - Action: Triggers Clarification Workflow. Demands additional medical tests (e.g., TMT, 2D Echo).
* **75+ points**: **Decline**
  - Action: Issue Repudiation/Decline Letter.

### D. Premium Loading Logic Example (Python-style)
```python
def calculate_premium_loading(base_premium: float, risk_factors: dict) -> float:
    loading_percentage = 0.0
    
    if risk_factors.get("bmi", 22) > 30:
        loading_percentage += 0.10  # 10% Obesity loading
        
    if risk_factors.get("smoker", False) and risk_factors.get("systolic_bp", 120) > 140:
        loading_percentage += 0.20  # 20% Compound loading for smoking + HTN
        
    if risk_factors.get("hba1c", 5.0) > 6.5:
        loading_percentage += 0.15  # 15% Diabetic loading
        
    # Cap maximum loading at 50%
    loading_percentage = min(loading_percentage, 0.50)
    
    return base_premium * (1 + loading_percentage)
```
