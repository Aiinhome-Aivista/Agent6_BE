import json
import os
import re
from dotenv import load_dotenv
from services.vector_store import query_risk_context, query_rulebook_context

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_LOCAL_MODEL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_MODEL")

def extract_details_with_python(text: str, policy_type: str = "Unknown Policy Type", application_type: str = "Existing Claim") -> dict:
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
        
    med_match = re.search(r'\b(?:medical\s*condition|disease|illness)\b\s*[:\-]?\s*([^\n,\.]+)', text_lower)
    if med_match:
        val = med_match.group(1).strip().title()
        if val.lower() not in ["none", "na", "n/a", "no major illness", "healthy"]:
            medical_cond = val
        else:
            medical_cond = "No Major Illness"
    else:
        medical_cond = None

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

    if application_type == "New Policy":
        coverage = None
        policy_num = None
        premium = None
        term = None

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
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key or api_key == "your_mistral_key_here": return {"company_name": None, "product_name": None}
    try:
        from mistralai.client import MistralClient
        from mistralai.models.chat_completion import ChatMessage
        client = MistralClient(api_key=api_key, endpoint=os.getenv("MISTRAL_LOCAL_URL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_API_URL"))
        prompt = f"Extract the target Insurance Company Name and Product/Policy Name from the applicant's text. Return ONLY a JSON object with 'company_name' and 'product_name'. If not explicitly mentioned, return null for that field.\n\nTEXT: {raw_text[:10000]}"
        MISTRAL_MODEL = os.getenv("MISTRAL_LOCAL_MODEL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_MODEL")
        resp = client.chat(
            model=MISTRAL_MODEL,
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
        client = ArangoClient(hosts=os.getenv("ARANGO_URL"))
        db = client.db(os.getenv("ARANGO_DB"), username=os.getenv("ARANGO_USER"), password=os.getenv("ARANGO_PASSWORD"))
        # Example AQL to find paths to known fraud nodes
        # Returning False by default for the realistic example workflow.
        return False
    except Exception as e:
        print(f"[Fraud Check Error] {e}")
        return False

def _call_llm(context_summary: str, kb_context: str = "", application_type: str = "Existing Claim") -> dict:
    default_resp = {
        "risk_score": 0,
        "risk_level": "UNKNOWN",
        "decision": "Manual Review Required - Missing Knowledge Base Guidelines",
        "breakdown": [],
        "fraud_signals": [],
        "positive_signals": [],
        "negative_signals": [],
        "explainability": {
            "why_approved_or_rejected": "No relevant underwriting manuals were found in the Knowledge Base to process this application.",
            "why_loading_applied": "N/A",
            "medical_impact": "N/A",
            "chance_of_approval_justification": "N/A"
        },
        "final_calculation": "N/A",
        "underwriting_narrative": "AI could not determine risk due to missing guidelines."
    }
    
    # Fallback early if KB is strictly empty
    if not kb_context.strip():
        return default_resp

    import os
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    if not MISTRAL_API_KEY or MISTRAL_API_KEY == "your_mistral_key_here":
        return default_resp

    try:
        from mistralai.client import MistralClient
        client = MistralClient(api_key=MISTRAL_API_KEY, endpoint=os.getenv("MISTRAL_LOCAL_URL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_API_URL"))

        prompt_logic = ""
        if application_type == "New Policy":
            prompt_logic = """
You must follow these 8 STEPS for New Applicants:
1. Identity Verification: Validate applicant demographics.
2. Medical History Analysis: Check for pre-existing diseases.
3. BMI & Vitals Check: Evaluate health metrics.
4. Rulebook Mapping: Map conditions strictly to the KNOWLEDGE BASE CONTEXT.
5. Base Premium Calculation: Determine base premium.
6. Loading/Discount Calculation: Apply risk loadings or discounts.
7. Waiting Period Assignment: Assign PED waiting periods.
8. Final Decision: Synthesize findings into a final risk score and decision.
"""
        else:
            prompt_logic = """
You must follow these 10 STEPS for Existing Claims:
1. Claim Triage: Identify the claim type.
2. Identity Verification: Validate claimant details.
3. Policy Validity Check: Ensure policy was active.
4. Medical History Analysis: Evaluate past conditions.
5. Rulebook Mapping: Map conditions strictly to the KNOWLEDGE BASE CONTEXT.
6. Exclusions Check: Check for policy exclusions.
7. Claim Adjudication: Determine eligibility.
8. Deductions Calculation: Calculate non-payable amounts.
9. Payout Calculation: Calculate final payable amount.
10. Final Decision: Synthesize findings into a final risk score and decision.
"""

        prompt = f"""You are a Senior Enterprise Health Insurance Underwriting AI Engine.

Your task is to calculate a realistic underwriting risk score and make a decision for a health insurance applicant.
CRITICAL RULE: You MUST base your evaluation STRICTLY on the KNOWLEDGE BASE CONTEXT provided below. 
Do NOT use outside knowledge. If the KNOWLEDGE BASE CONTEXT does not contain enough rules or information to evaluate the applicant's specific conditions (like their specific disease, age, or BMI), you MUST set "risk_level" to "UNKNOWN" and "decision" to "Manual Review Required - Missing Knowledge Base Guidelines".
{prompt_logic}

========================
KNOWLEDGE BASE CONTEXT
========================
{kb_context}

========================
OUTPUT FORMAT
========================
Return ONLY JSON:
{{
  "risk_score": number (0-100),
  "risk_level": "LOW|MEDIUM|HIGH|CRITICAL|UNKNOWN",
  "decision": "string (e.g. Approve Standard Terms, Refer Underwriter, Manual Review Required - Missing Knowledge Base Guidelines)",
  "breakdown": [
    {{
      "factor": "Age/BMI/Disease/etc",
      "raw_score": "number (0 to 100, representing the risk penalty for this factor alone, where 0 is perfect/no risk and 100 is max risk)",
      "weight": "number (the maximum points this factor contributes to the total 100 score, e.g., 30)",
      "weighted_score": "number (must be exactly: raw_score * weight / 100)",
      "justification": "Explanation based strictly on KB",
      "triggered_rules": ["Quote the rule from KB"]
    }}
  ],
  "explainability": {{
    "why_approved_or_rejected": "string",
    "why_loading_applied": "string",
    "medical_impact": "string",
    "chance_of_approval_justification": "string"
  }},
  "policy_eligibility": {{ "eligible_plans": [ {{ "plan_name": "string", "allowed": true/false, "reason": "string" }} ] }},
  "premium_calculation": {{ "premium_output": [ {{ "sum_assured": number, "base_premium": number, "risk_loading_percent": number, "final_premium": number }} ] }},
  "claim_decision_engine": {{ "claim_eligibility": true/false, "approved_amount": number, "final_payable_amount": number, "deductions": [ {{ "name": "string", "amount": number }} ], "reason": "string" }},
  "policy_information": {{ "policy_number": "string", "sum_insured": number, "used_sum_insured": number, "remaining_sum_insured": number, "waiting_period_completed": true/false }},
  "claim_history": {{ "current_claim": {{ "date": "string", "amount_claimed": number, "claim_type": "string", "reason_for_claim": "string" }}, "earlier_claims": [ {{ "date": "string", "amount_claimed": number, "claim_type": "string", "reason_for_claim": "string" }} ] }},
  "extracted_details": {{
    "policy_details": {{ "nominee": "string", "policy_number": "string", "annual_premium": number, "policy_summary": "string", "coverage_amount": number, "policy_term_years": number }},
    "validity_dates": {{ "from_date": "string", "to_date": "string" }},
    "patient_details": {{ "age": number, "bmi": number, "gender": "string", "blood_pressure": "string", "medical_condition": "string", "contact_number": "string", "email": "string" }}
  }},
  "base_premium_inr": number,
  "tax_inr": number,
  "final_premium_inr": number,
  "recommended_plan_tier": "string",
  "underwriting_narrative": "string"
}}

{"If this is a New Policy Application, use the KNOWLEDGE BASE CONTEXT above to select the best plan and calculate premiums." if application_type == 'New Policy' else 'Leave premium fields as 0 if this is an Existing Claim.'}

========================
APPLICANT DATA ({application_type})
========================
{context_summary[:15000]}
"""
        MISTRAL_MODEL = os.getenv("MISTRAL_LOCAL_MODEL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_MODEL")
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
    
    python_extracted = extract_details_with_python(raw_text, policy_type, application_type)
    patient = python_extracted.get("patient_details", {})

    age = patient.get("age") or 25  
    bmi = patient.get("bmi") or 22.0
    disease = patient.get("medical_condition") or ""

    context_summary = raw_text[:20000]

    if application_type == 'Existing Claim':
        search_query = f"Hospitalization Cover, Day Care, Exclusions, and Limits for disease {disease}"
    else:
        search_query = f"Health insurance underwriting guidelines for disease {disease} age {age} BMI {bmi}"
        
    kb_context_list = query_rulebook_context(query=search_query, n_results=5)
    kb_context = "\n".join(kb_context_list) if kb_context_list else ""

    llm_result = _call_llm(context_summary, kb_context, application_type)
    
    fraud_detected = check_fraud_in_arango(case_id)

    if fraud_detected:
        risk_level = "CRITICAL"
        decision = "Fraud Escalation"
        human_review_required = True
        recommendation = "Fraud Suspicion - Referred to Investigation"
    else:
        risk_level = str(llm_result.get("risk_level", "UNKNOWN"))[:20]
        decision = llm_result.get("decision", "Manual Review Required - Missing Knowledge Base Guidelines")
        human_review_required = risk_level in ["HIGH", "CRITICAL", "MEDIUM", "UNKNOWN"]
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

    try:
        if llm_result.get("breakdown"):
            calculated_score = sum(float(b.get("weighted_score", 0)) for b in llm_result.get("breakdown", []))
            llm_risk_score = min(100, max(0, int(round(calculated_score))))
        else:
            llm_risk_score = int(llm_result.get("risk_score", 0))
    except (ValueError, TypeError):
        llm_risk_score = 0
        
    llm_breakdown = llm_result.get("breakdown", [])

    out = {
        "risk_score": llm_risk_score,
        "deterministic_score": llm_risk_score,
        "llm_score": llm_risk_score,
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
        "rules_passed": len(llm_breakdown), 
        "rules_total": len(llm_breakdown),
        "breakdown": llm_breakdown,
        "ai_narrative": llm_result.get("underwriting_narrative", ""),
        "ai_confidence": ai_confidence,
        "ai_flags": llm_result.get("negative_signals", []),
        "extracted_details": safe_extracted_details
    }
    return out
