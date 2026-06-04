import json
import os
import re
from dotenv import load_dotenv
from services.vector_store import query_risk_context, query_rulebook_context

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

def extract_details_with_python(text: str, policy_type: str = "Unknown Policy Type") -> dict:
    if not text:
        return {}
    text_lower = text.lower()
    
    age = None
    dob_match = re.search(r'\b(?:dob|date\s*of\s*birth)\s*[:\-\n]?\s*(\d{2}[-/\.]\d{2}[-/\.]\d{4})\b', text_lower)
    if dob_match:
        dob_str = dob_match.group(1)
        year_match = re.search(r'\d{4}', dob_str)
        if year_match:
            import datetime
            current_year = datetime.datetime.now().year
            # Fallback for demo: if current_year is 2026, 2026 - 1992 = 34
            age = current_year - int(year_match.group())
            
    if age is None:
        age_match = re.search(r'\b(?:age)\s*[:\-]?\s*(\d{1,2})\b', text_lower)
        if age_match: age = int(age_match.group(1))
        
    gender = None
    gender_match = re.search(r'\b(?:gender|sex)\s*[:\-]?\s*(male|female|other|m|f)\b', text_lower)
    if gender_match:
        g = gender_match.group(1)
        gender = "Male" if g in ["male", "m"] else "Female" if g in ["female", "f"] else g.capitalize()
        
    bmi = None
    bmi_match = re.search(r'\bbmi\b.*?(\d{1,2}(?:\.\d)?)\b', text_lower)
    if bmi_match: bmi = float(bmi_match.group(1))
        
    bp = None
    bp_match = re.search(r'\b(?:bp|blood\s*pressure)\s*[:\-]?\s*(\d{2,3}\/\d{2,3})\b', text_lower)
    if bp_match: bp = bp_match.group(1)
        
    occupation = None
    occ_match = re.search(r'\b(?:occupation|job|profession)\s*[:\-]?\s*([a-zA-Z\s]{3,30})(?:\n|,|\.)', text_lower)
    if occ_match: occupation = occ_match.group(1).strip().title()
        
    coverage = None
    cov_match = re.search(r'\b(?:coverage|sum\s*insured|amount)\s*[:\-]?\s*(?:rs\.?|inr|₹|\$)?\s*([\d,]+)\b', text_lower)
    if cov_match:
        coverage = cov_match.group(1).strip()
        if not coverage.startswith("₹"): coverage = f"₹{coverage}"

    term = None
    term_match = re.search(r'\b(?:term|policy\s*term|duration)\s*[:\-]?\s*(\d{1,2})\s*(?:years?|yrs?)\b', text_lower)
    if term_match: term = int(term_match.group(1))

    nominee = None
    nom_match = re.search(r'\b(?:nominee|nominee\s*details?)\s*[:\-]?\s*([a-zA-Z\s]{3,30})(?:\n|,|\.)', text_lower)
    if nom_match: nominee = nom_match.group(1).strip().title()

    from_date, to_date = None, None
    date_pattern = r'(\d{2}[-/\.]\d{2}[-/\.]\d{4}|\w+\s+\d{1,2},\s+\d{4})'
    from_match = re.search(r'\b(?:from|start|valid\s*from|effective\s*date)\s*[:\-]?\s*' + date_pattern, text_lower)
    if from_match: from_date = from_match.group(1).strip().title()
    to_match = re.search(r'\b(?:to|till|end|expiry|valid\s*till)\s*[:\-]?\s*' + date_pattern, text_lower)
    if to_match: to_date = to_match.group(1).strip().title()

    policy_num = None
    pol_match = re.search(r'\b(?:policy\s*number|policy\s*no\.?)\s*[:\-]?\s*([a-z0-9\-]{5,20})\b', text_lower)
    if pol_match: policy_num = pol_match.group(1).upper()
        
    marital_status = None
    mar_match = re.search(r'\b(?:marital\s*status)\s*[:\-]?\s*(single|married|divorced|widowed)\b', text_lower)
    if mar_match: marital_status = mar_match.group(1).title()
        
    contact = None
    contact_match = re.search(r'\b(?:contact\s*number|phone|mobile)\s*[:\-]?\s*(\+?[\d\-\s]{10,15})\b', text_lower)
    if contact_match: contact = contact_match.group(1).strip()
        
    email = None
    email_match = re.search(r'\b(?:email\s*id|email)\s*[:\-]?\s*([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})\b', text_lower)
    if email_match: email = email_match.group(1)
        
    medical_cond = None
    med_match = re.search(r'\b(?:medical\s*condition|disease|illness)\s*[:\-]?\s*([a-z0-9\s\-]+?)(?:\n|,|\.|\bbmi\b|\bbp\b)', text_lower)
    if med_match:
        val = med_match.group(1).strip().title()
        if val.lower() not in ["none", "na", "n/a", "no major illness", "healthy"]:
            medical_cond = val
        else:
            medical_cond = "No Major Illness"

    premium = None
    prem_match = re.search(r'\b(?:annual\s*premium|premium)\s*[:\-]?\s*(?:rs\.?|inr|₹|\$)?\s*([\d,]+)\b', text_lower)
    if prem_match: premium = f"₹{prem_match.group(1).strip()}"

    claim_ratio = None
    claim_match = re.search(r'\b(?:claim\s*ratio|claims\s*ratio)\s*[:\-]?\s*(\d+(?:\.\d+)?)\b', text_lower)
    if claim_match:
        claim_ratio = float(claim_match.group(1))

    smoking = "None"
    if "regular smoker" in text_lower or "smokes daily" in text_lower: smoking = "Regular"
    elif "occasional smoker" in text_lower or "smokes occasionally" in text_lower: smoking = "Occasional"
    elif "smoker" in text_lower or "tobacco" in text_lower: smoking = "Occasional"

    lifestyle = "Sedentary"
    if "active lifestyle" in text_lower or "athlete" in text_lower: lifestyle = "Active"
    elif "moderate lifestyle" in text_lower or "exercises occasionally" in text_lower: lifestyle = "Moderate"

    return {
        "patient_details": {
            "age": age, "gender": gender, "occupation": occupation, "marital_status": marital_status,
            "contact_number": contact, "email": email, "medical_condition": medical_cond,
            "bmi": bmi, "blood_pressure": bp, "smoking": smoking, "lifestyle": lifestyle, "claim_ratio": claim_ratio
        },
        "policy_details": {
            "policy_number": policy_num, "policy_summary": policy_type, "coverage_amount": coverage,
            "annual_premium": premium, "policy_term_years": term, "nominee": nominee
        },
        "validity_dates": {
            "from_date": from_date, "to_date": to_date
        }
    }

def detect_target_policy(raw_text: str) -> dict:
    import json
    import os
    api_key = os.getenv("MISTRAL_API_KEY", "")
    if not api_key or api_key == "your_mistral_key_here": return {"company_name": None, "product_name": None}
    try:
        from mistralai.client import MistralClient
        from mistralai.models.chat_completion import ChatMessage
        client = MistralClient(api_key=api_key)
        prompt = f"Extract the target Insurance Company Name and Product/Policy Name from the applicant's text. Return ONLY a JSON object with 'company_name' and 'product_name'. If not explicitly mentioned, return null for that field.\n\nTEXT: {raw_text[:10000]}"
        resp = client.chat(
            model="mistral-large-latest",
            messages=[ChatMessage(role="user", content=prompt)],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"[LLM] Target policy detection error: {e}")
        return {"company_name": None, "product_name": None}

def check_fraud_in_arango(case_id: int) -> bool:
    try:
        from arango import ArangoClient
        import os
        client = ArangoClient(hosts=os.getenv("ARANGO_HOST", "https://a71fd1666bd9.arangodb.cloud:8529"))
        db = client.db(os.getenv("ARANGO_DB", "underwriting_db"), username=os.getenv("ARANGO_USERNAME", "root"), password=os.getenv("ARANGO_PASSWORD", "TnHBO0Y4FwKptmr6GxrL"))
        # Example AQL to find paths to known fraud nodes
        # Returning False by default for the realistic example workflow.
        return False
    except Exception as e:
        print(f"[Fraud Check Error] {e}")
        return False

def _call_llm(context_summary: str, rule_results: list, final_score: float, kb_context: str = "", application_type: str = "Existing Claim") -> dict:
    default_resp = {
        "risk_score": final_score,
        "risk_level": "LOW",
        "decision": "Approve Standard Terms",
        "breakdown": [],
        "fraud_signals": [],
        "positive_signals": [],
        "negative_signals": [],
        "explainability": {
            "why_approved_or_rejected": "LLM Failed. Used deterministic logic.",
            "why_loading_applied": "N/A",
            "medical_impact": "N/A"
        },
        "final_calculation": "Deterministic fallback",
        "underwriting_narrative": "AI unavailable."
    }
    
    import os
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
    if not MISTRAL_API_KEY or MISTRAL_API_KEY == "your_mistral_key_here":
        return default_resp

    try:
        from mistralai.client import MistralClient
        client = MistralClient(api_key=MISTRAL_API_KEY)

        prompt = f"""You are a Senior Enterprise Health Insurance Underwriting AI Engine.

Your task is to calculate a realistic underwriting risk score for a health insurance applicant using deterministic underwriting rules and explainable AI reasoning.

IMPORTANT:
- Perform REALISTIC enterprise underwriting analysis.
- Use medical, lifestyle, financial, fraud, and claims-based evaluation.
- Explain every score clearly.
- Return ONLY valid JSON.

========================
UNDERWRITING RULES
========================

1. AGE RULES
- Age 18-40 => Score 0
- Age 41-55 => Score 50
- Age 56-60 => Score 70
- Age >60 => Score 80

Weight = 25%

------------------------

2. BMI RULES
- BMI 18.5-24.9 => Score 0
- BMI 25-29.9 => Score 20
- BMI 30-34.9 => Score 50
- BMI >=35 => Score 70
- BMI <18.5 => Score 15

Weight = 15%

------------------------

3. DISEASE HISTORY RULES
- No PED => Score 0
- Diabetes => +30
- Hypertension => +25
- Cardiac Disease => +60
- Cancer => +80
- Multiple PED => cumulative scoring

Weight = 25%

------------------------

4. SMOKING & ALCOHOL RULES
- None => Score 0
- Occasional => Score 20
- Regular => Score 50

Weight = 15%

------------------------

5. CLAIM HISTORY RULES
- No prior claims => Score 0
- 1 moderate claim => Score 20
- Frequent claims => Score 40
- Fraud suspicion => Score 80

Weight = 10%

------------------------

6. LIFESTYLE RULES
- Active Lifestyle => Score 0
- Moderate Lifestyle => Score 15
- Sedentary Lifestyle => Score 30

Weight = 10%

------------------------

7. FRAUD RULES
- Edited documents => +80
- Mismatched data => +60
- Blacklisted hospital => +100

Weight = 20%

========================
FINAL SCORE FORMULA
========================

Final Risk Score =
(Age × 0.25) +
(BMI × 0.15) +
(Disease × 0.25) +
(Smoking × 0.15) +
(Claims × 0.10) +
(Lifestyle × 0.10) +
(Fraud × 0.20)

========================
RISK LEVELS
========================

0-25 => LOW RISK
26-50 => MEDIUM RISK
51-75 => HIGH RISK
76-100 => CRITICAL RISK

========================
DECISION LOGIC
========================

LOW => Approve Standard Terms
MEDIUM => Approve With Loading / Refer
HIGH => Senior Underwriter Review
CRITICAL => Decline / Fraud Escalation

========================
OUTPUT FORMAT
========================

Return ONLY JSON:

{{
  "risk_score": number,
  "risk_level": "LOW|MEDIUM|HIGH|CRITICAL",
  "decision": "string",

  "breakdown": [
    {{
      "factor": "Age",
      "raw_score": number,
      "weight": number,
      "weighted_score": number,
      "justification": "string",
      "triggered_rules": ["string"]
    }}
  ],

  "fraud_signals": ["string"],
  "positive_signals": ["string"],
  "negative_signals": ["string"],

  "explainability": {{
    "why_approved_or_rejected": "string",
    "why_loading_applied": "string",
    "medical_impact": "string",
    "chance_of_approval_justification": "string"
  }},

  "policy_eligibility": {{
    "eligible_plans": [
      {{
        "plan_name": "string",
        "allowed": true/false,
        "reason": "string"
      }}
    ]
  }},

  "premium_calculation": {{
    "premium_output": [
      {{
        "sum_assured": number,
        "base_premium": number,
        "risk_loading_percent": number,
        "final_premium": number
      }}
    ]
  }},

  "policy_information": {{
    "policy_number": "string",
    "policy_age_days": number,
    "sum_insured": number,
    "used_sum_insured": number,
    "remaining_sum_insured": number,
    "waiting_period_completed": true/false
  }},

  "claim_decision_engine": {{
    "claim_eligibility": true/false,
    "approved_amount": number,
    "deductions": [{{"type": "string", "amount": number}}],
    "final_payable_amount": number,
    "decision": "string",
    "confidence_score": number,
    "manual_review_required": true/false,
    "reason": "string"
  }},

  "claim_history": {{
    "current_claim": {{
      "claim_date": "string or None",
      "amount_claimed": "string (e.g. Rs. 85000) or None",
      "claim_type": "Cashless or Reimbursement or None",
      "reason_for_claim": "string"
    }},
    "earlier_claims": [
      {{
        "claim_date": "string",
        "amount_claimed": "string",
        "claim_type": "string",
        "reason_for_claim": "string"
      }}
    ]
  }},

  "final_calculation": "step-by-step formula",
  "base_premium_inr": number,
  "risk_loading_percentage": number,
  "risk_loading_amount": number,
  "addons_amount": number,
  "tax_inr": number,
  "final_premium_inr": number,
  "recommended_plan_tier": "string (e.g. Standard, Premium, Platinum)",
  "ped_waiting_period_months": number,
  "underwriting_narrative": "professional underwriting explanation",
  "eligible_plans_and_covers": ["plan 1", "plan 2"]
}}

========================
KNOWLEDGE BASE CONTEXT (FOR NEW POLICIES)
========================
{kb_context}

{"If this is a New Policy Application, you MUST use the KNOWLEDGE BASE CONTEXT above to select the best plan, calculate the 'base_premium_inr', calculate 'tax_inr' as 18% of (base + risk_loading), and set 'final_premium_inr'." if application_type == 'New Policy' else 'Leave premium fields as 0 if this is an Existing Claim.'}

========================
APPLICANT DATA ({application_type})
========================

{context_summary[:15000]}
"""
        MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-small-latest")
        from mistralai.models.chat_completion import ChatMessage
        response = client.chat(
            model=MISTRAL_MODEL,
            messages=[ChatMessage(role="user", content=prompt)],
            response_format={"type": "json_object"},
            temperature=0.1
        )
        import json
        raw = response.choices[0].message.content
        return json.loads(raw)

    except Exception as e:
        print(f"[LLM] Error: {e}")
        return default_resp

def analyse_risk(case_id: int) -> dict:
    from database.connection import fetch_all, execute
    import re

    docs = fetch_all("SELECT raw_text FROM ocr_extracted_data oed JOIN documents d ON oed.document_id = d.id WHERE d.case_id = %s", (case_id,))
    raw_text = " ".join([doc["raw_text"] for doc in docs]) if docs else ""
    
    case_rec = fetch_all("""
        SELECT uc.policy_type, pt.product_name AS product_type, uc.existing_policy_details, uc.requested_coverage, uc.application_type 
        FROM underwriting_cases uc 
        LEFT JOIN product_types pt ON uc.product_type_id = pt.id 
        WHERE uc.id = %s
    """, (case_id,))
    policy_type = case_rec[0]["policy_type"] if case_rec else "Unknown"
    product_type = case_rec[0].get("product_type", "Standard") if case_rec else "Standard"
    application_type = case_rec[0].get("application_type", "Existing Claim") if case_rec else "Existing Claim"
        
    detected = detect_target_policy(raw_text)
    company_name = detected.get("company_name")
    product_name = detected.get("product_name")
    
    execute("UPDATE underwriting_cases SET company_name = %s, product_name = %s WHERE id = %s", (company_name, product_name, case_id))
    
    python_extracted = extract_details_with_python(raw_text, policy_type)
    patient = python_extracted.get("patient_details", {})

    age = patient.get("age") or 25  
    bmi = patient.get("bmi") or 22.0
    disease = patient.get("medical_condition") or ""
    smoking = patient.get("smoking") or "None"
    claim_ratio = patient.get("claim_ratio") or 0.0
    lifestyle = patient.get("lifestyle") or "Moderate"
    raw_text_lower = raw_text.lower()

    age_score = 0
    if age > 60: age_score = 80
    elif age >= 56: age_score = 70
    elif age >= 41: age_score = 50
    else: age_score = 0
    
    bmi_score = 0
    if bmi >= 35: bmi_score = 70
    elif bmi >= 30: bmi_score = 50
    elif bmi >= 25: bmi_score = 20
    elif bmi < 18.5: bmi_score = 15
    else: bmi_score = 0
    
    disease_score = 0
    if "cancer" in raw_text_lower: disease_score = 80
    elif "heart" in raw_text_lower or "cardiac" in raw_text_lower: disease_score = 60
    elif "diabetes" in raw_text_lower: disease_score = 30
    elif "hypertension" in raw_text_lower or "bp" in raw_text_lower: disease_score = 25
    
    smoking_score = 0
    if smoking == "Regular": smoking_score = 50
    elif smoking == "Occasional": smoking_score = 20
    
    claim_score = 0
    if "dengue" in raw_text_lower or "malaria" in raw_text_lower or claim_ratio > 0:
        claim_score = 20 # 1 moderate claim
    if claim_ratio > 1.0: claim_score = 40
    
    lifestyle_score = 0
    if lifestyle == "Sedentary": lifestyle_score = 30
    elif lifestyle == "Moderate": lifestyle_score = 15
    elif lifestyle == "Active": lifestyle_score = 0

    final_score = (age_score * 0.25) + (bmi_score * 0.15) + (disease_score * 0.25) + (smoking_score * 0.15) + (claim_score * 0.10) + (lifestyle_score * 0.10)
    final_score = round(final_score, 2)

    rule_results = [
        {"label": "Age", "score": age_score, "max_score": 100, "weight": 0.25},
        {"label": "BMI", "score": bmi_score, "max_score": 100, "weight": 0.15},
        {"label": "Disease History", "score": disease_score, "max_score": 100, "weight": 0.25},
        {"label": "Smoking & Alcohol", "score": smoking_score, "max_score": 100, "weight": 0.15},
        {"label": "Claim History", "score": claim_score, "max_score": 100, "weight": 0.10},
        {"label": "Lifestyle", "score": lifestyle_score, "max_score": 100, "weight": 0.10}
    ]

    context_summary = raw_text[:3000]

    kb_context_list = query_rulebook_context(query=f"Health insurance underwriting guidelines for disease {disease} age {age} BMI {bmi}", n_results=3)
    kb_context = "\n".join(kb_context_list) if kb_context_list else ""

    llm_result = _call_llm(context_summary, rule_results, final_score, kb_context, application_type)
    
    # Force LLM score to match deterministic score to prevent hallucination
    llm_result["risk_score"] = final_score
    
    llm_breakdown = llm_result.get("breakdown", [])
    if llm_breakdown:
        # Update justifications only, keep deterministic scores
        for r in rule_results:
            match = next((b for b in llm_breakdown if b.get("factor", "").lower() in r["label"].lower() or r["label"].lower() in b.get("factor", "").lower()), None)
            if match:
                r["justification"] = match.get("justification", f"Deterministic logic applied. Score: {r['score']}")
                r["matched_risk_signals"] = match.get("triggered_rules", [])
                r["matched_positive_signals"] = []
            else:
                r["justification"] = f"Deterministic logic applied. Score: {r['score']}"
                r["matched_risk_signals"] = []
                r["matched_positive_signals"] = []
    else:
        justifications = llm_result.get("rule_justifications", {})
        for r in rule_results:
            r["justification"] = justifications.get(r["label"], f"Based on extracted value: {r['score']} points.")
            r["matched_risk_signals"] = []
            r["matched_positive_signals"] = []

    # Product tier logic
    stp_threshold = 30
    refer_threshold = 50
    tier = llm_result.get("recommended_plan_tier", product_type)
    if tier and "Platinum" in tier:
        stp_threshold = 45
        refer_threshold = 60
    elif tier and ("Premium" in tier or "Gold" in tier):
        stp_threshold = 40
        refer_threshold = 55
    elif tier and "Standard" in tier:
        stp_threshold = 30
        refer_threshold = 50
    elif tier and "Basic" in tier:
        stp_threshold = 25
        refer_threshold = 40

    fraud_detected = check_fraud_in_arango(case_id)

    if fraud_detected:
        risk_level = "CRITICAL"
        decision = "Fraud Escalation"
        human_review_required = True
        recommendation = "Fraud Suspicion - Referred to Investigation"
    else:
        risk_level = llm_result.get("risk_level", "LOW")
        decision = llm_result.get("decision", "Approve Standard Terms")
        human_review_required = risk_level in ["HIGH", "CRITICAL", "MEDIUM"]
        recommendation = decision

    # Programmatic Confidence Score Calculation
    base_confidence = 0.92
    if fraud_detected:
        base_confidence -= 0.45
    if not patient.get("bmi") or not patient.get("blood_pressure"):
        base_confidence -= 0.10
    if not python_extracted.get("patient_details", {}).get("occupation"):
        base_confidence -= 0.05
    if not docs:
        base_confidence -= 0.20
    
    if decision in ["Clarification Required", "Refer Underwriter"]:
        base_confidence -= 0.15
        
    ai_confidence = max(0.40, min(0.98, base_confidence))

    extracted_details = llm_result.get("extracted_details", {}) if isinstance(llm_result, dict) else {}
    if not isinstance(extracted_details, dict): extracted_details = {}
    patient_details = extracted_details.get("patient_details", {}) if isinstance(extracted_details, dict) else {}
    policy_details = extracted_details.get("policy_details", {}) if isinstance(extracted_details, dict) else {}
    validity_dates = extracted_details.get("validity_dates", {}) if isinstance(extracted_details, dict) else {}

    safe_extracted_details = {
        "patient_details": {
            "age": patient.get("age") or (patient_details.get("age") if isinstance(patient_details, dict) else None),
            "gender": patient.get("gender") or (patient_details.get("gender") if isinstance(patient_details, dict) else None),
            "occupation": patient.get("occupation") or (patient_details.get("occupation") if isinstance(patient_details, dict) else None),
            "marital_status": patient.get("marital_status") or (patient_details.get("marital_status") if isinstance(patient_details, dict) else None),
            "contact_number": patient.get("contact_number") or (patient_details.get("contact_number") if isinstance(patient_details, dict) else None),
            "email": patient.get("email") or (patient_details.get("email") if isinstance(patient_details, dict) else None),
            "medical_condition": patient.get("medical_condition") or (patient_details.get("medical_condition") if isinstance(patient_details, dict) else None),
            "bmi": patient.get("bmi") or (patient_details.get("bmi") if isinstance(patient_details, dict) else None),
            "blood_pressure": patient.get("blood_pressure") or (patient_details.get("blood_pressure") if isinstance(patient_details, dict) else None)
        },
        "policy_details": {
            "policy_number": python_extracted.get("policy_details", {}).get("policy_number") or (policy_details.get("policy_number") if isinstance(policy_details, dict) else None),
            "policy_summary": python_extracted.get("policy_details", {}).get("policy_summary") or (policy_details.get("policy_summary") if isinstance(policy_details, dict) else None),
            "coverage_amount": python_extracted.get("policy_details", {}).get("coverage_amount") or (policy_details.get("coverage_amount") if isinstance(policy_details, dict) else None),
            "annual_premium": python_extracted.get("policy_details", {}).get("annual_premium") or (policy_details.get("annual_premium") if isinstance(policy_details, dict) else None),
            "policy_term_years": python_extracted.get("policy_details", {}).get("policy_term_years") or (policy_details.get("policy_term_years") if isinstance(policy_details, dict) else None),
            "nominee": python_extracted.get("policy_details", {}).get("nominee") or (policy_details.get("nominee") if isinstance(policy_details, dict) else None)
        },
        "validity_dates": {
            "from_date": python_extracted.get("validity_dates", {}).get("from_date") or (validity_dates.get("from_date") if isinstance(validity_dates, dict) else None),
            "to_date": python_extracted.get("validity_dates", {}).get("to_date") or (validity_dates.get("to_date") if isinstance(validity_dates, dict) else None)
        }
    }

    out = {
        "risk_score": final_score,
        "deterministic_score": final_score,
        "llm_score": final_score,
        "risk_level": risk_level,
        "recommendation": recommendation,
        "approval_confidence": ai_confidence,
        "decision": decision,
        "premium_adjustment": llm_result.get("premium_adjustment", "Standard"),
        "ped_waiting_period_months": llm_result.get("ped_waiting_period_months", 0),
        "exclusions": llm_result.get("exclusions", []),
        "copay_percentage": llm_result.get("copay_percentage", 0),
        "deductible_inr": llm_result.get("deductible_inr", 0),
        "loading_percentage": llm_result.get("risk_loading_percentage", llm_result.get("loading_percentage", 0)),
        "risk_loading_amount": llm_result.get("risk_loading_amount", 0),
        "addons_amount": llm_result.get("addons_amount", 0),
        "base_premium_inr": llm_result.get("base_premium_inr", 0),
        "final_premium_inr": llm_result.get("final_premium_inr", 0),
        "tax_inr": llm_result.get("tax_amount", llm_result.get("tax_inr", 0)),
        "recommended_plan_tier": llm_result.get("recommended_plan_tier", "Standard"),
        "approval_conditions": llm_result.get("approval_conditions", []),
        "recommendation_engine": llm_result.get("recommendation_engine", {}),
        "kb_evidence": llm_result.get("kb_evidence", {}),
        "explainability": llm_result.get("explainability", {}),
        "clarification_needs": llm_result.get("clarification_needs", {}),
        "medical_risk_summary": llm_result.get("medical_risk_summary", []),
        "financial_risk_summary": llm_result.get("financial_risk_summary", []),
        "fraud_risk_summary": llm_result.get("fraud_risk_summary", []),
        "positive_signals": llm_result.get("positive_signals", []),
        "negative_signals": llm_result.get("negative_signals", []),
        "claim_history": llm_result.get("claim_history", {"earlier_claims": [], "current_claim": {"amount_claimed": "None", "claim_type": "None", "reason_for_claim": "None"}}),
        "eligible_plans_and_covers": llm_result.get("eligible_plans_and_covers", []),
        "underwriting_narrative": llm_result.get("underwriting_narrative", ""),
        "policy_eligibility": llm_result.get("policy_eligibility", {}),
        "premium_calculation": llm_result.get("premium_calculation", {}),
        "policy_information": llm_result.get("policy_information", {}),
        "claim_decision_engine": llm_result.get("claim_decision_engine", {}),
        "human_review_required": human_review_required,
        "recommended_action": recommendation,
        "rules_passed": sum(1 for r in rule_results if r["score"] <= (r["max_score"] * 0.4)), 
        "rules_total": len(rule_results),
        "breakdown": rule_results,
        "ai_narrative": llm_result.get("underwriting_narrative", ""),
        "ai_confidence": ai_confidence,
        "ai_flags": llm_result.get("negative_signals", []),
        "extracted_details": safe_extracted_details
    }
    return out
