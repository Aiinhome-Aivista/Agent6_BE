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

    aadhaar = None
    aadhaar_match = re.search(r'\b(\d{4}\s?\d{4}\s?\d{4})\b', text_lower)
    if aadhaar_match: aadhaar = aadhaar_match.group(1).replace(' ', '')

    pan = None
    pan_match = re.search(r'\b([a-zA-Z]{5}\d{4}[a-zA-Z])\b', text_lower)
    if pan_match: pan = pan_match.group(1).upper()

    if application_type == "New Policy":
        coverage = None
        policy_num = None
        premium = None
        term = None

    return {
        "patient_details": {
            "age": age, "gender": gender, "occupation": occupation, "marital_status": marital_status,
            "contact_number": contact, "email": email, "medical_condition": medical_cond,
            "bmi": bmi, "blood_pressure": bp, "smoking": smoking, "lifestyle": lifestyle, "claim_ratio": claim_ratio,
            "aadhaar": aadhaar, "pan": pan
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
        kwargs = {"api_key": api_key}
        if os.getenv("MISTRAL_MODE") == "Local":
            kwargs["endpoint"] = os.getenv("MISTRAL_LOCAL_URL")
        client = MistralClient(**kwargs)
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

def _call_llm(context_summary: str, kb_context: str = "", application_type: str = "Existing Claim", config_json: str = "[]") -> dict:
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
        kwargs = {"api_key": MISTRAL_API_KEY}
        if os.getenv("MISTRAL_MODE") == "Local":
            kwargs["endpoint"] = os.getenv("MISTRAL_LOCAL_URL")
        client = MistralClient(**kwargs)

        prompt_logic = ""
        if application_type == "New Policy":
            prompt_logic = """
--- AGENT 4: RISK ANALYSIS AGENT ---
1. Evaluate the applicant against the Rulebook.
2. Calculate a Risk Score from 1 to 100 (Higher = Riskier).
3. Identify exactly which rule was triggered.

--- AGENT 5: PRICING AGENT ---
4. Base Premium = $1000 (equivalent to ₹83,000 INR).
5. If Risk Score < 30: Apply 10% discount.
6. If Risk Score 30-70: Standard base premium.
7. If Risk Score > 70: Apply 25% loaded premium.

--- AGENT 6: DECISION AGENT (STP) ---
8. Rules for STP Auto-Approval:
   - Risk Score < 40
   - 0 Fraud Flags
   - 0 Missing Docs
9. If any rule fails, decision MUST be "Refer to Underwriter". If hard rules fail (e.g., Terminal Illness), decision MUST be "Decline".
"""
        else:
            prompt_logic = """
--- AGENT 4: RISK ANALYSIS AGENT ---
1. Evaluate the claimant against the Rulebook (Exclusions & Eligibility).
2. Calculate a Risk Score from 1 to 100 (Higher = Riskier) based on claim anomalies.

--- AGENT 5: PRICING / PAYOUT AGENT ---
3. Deductions Calculation: Calculate non-payable amounts.
4. Payout Calculation: Calculate final payable amount.

--- AGENT 6: DECISION AGENT (STP) ---
5. Determine if claim qualifies for auto-approval. If anomalies exist, "Refer to Underwriter".
"""

        prompt = f"""You are a Senior Enterprise Health Insurance Underwriting AI Engine.

Your task is to calculate a realistic underwriting risk score and make a decision for a health insurance applicant.
CRITICAL RULE: You MUST base your evaluation STRICTLY on the KNOWLEDGE BASE CONTEXT provided below. 
Do NOT use outside knowledge. If the KNOWLEDGE BASE CONTEXT does not contain enough rules or information to evaluate the applicant's specific conditions (like their specific disease, age, or BMI), you MUST set "risk_level" to "UNKNOWN" and "decision" to "Manual Review Required - Missing Knowledge Base Guidelines".

ADDITIONAL CRITICAL RULE: You are provided with a RISK SCORE PARAMETERIZATION JSON CONFIGURATION. You MUST use the weights specified in this JSON to evaluate Risk Score and Breakdown factors (specifically Medical History, Age, Height, Weight, Current Location, Travel History). 
IMPORTANT: DO NOT use BMI for risk scoring. Exclude BMI completely from the breakdown and risk calculation, and rely on Height and Weight instead, based on the provided JSON config.
{prompt_logic}

========================
RISK SCORE PARAMETERIZATION CONFIGURATION (JSON)
========================
{config_json}

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
      "triggered_rules": ["Quote the rule from KB"],
      "citations": ["Extract the exact SOURCE DOCUMENT filenames from the text that support this factor. If none, return empty array []"]
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
    "patient_details": {{ "age": number, "bmi": number, "gender": "string", "blood_pressure": "string", "medical_condition": "string", "contact_number": "string", "email": "string", "aadhaar": "string", "pan": "string" }}
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

def calculate_past_cases_comparison(case_id: int) -> dict:
    from database.connection import fetch_one, fetch_all
    import json
    import re
    # 1. Fetch current case details
    curr_case = fetch_one("""
        SELECT uc.id, uc.policy_type, uc.application_type, uc.requested_coverage, ra.findings
        FROM underwriting_cases uc
        LEFT JOIN risk_assessments ra ON ra.case_id = uc.id
        WHERE uc.id = %s
        ORDER BY ra.created_at DESC LIMIT 1
    """, (case_id,))
    
    if not curr_case:
        return {
            "acceptance_probability": 0.0,
            "rejection_probability": 0.0,
            "compared_cases_count": 0,
            "compared_cases": []
        }
    
    curr_policy = curr_case.get("policy_type")
    curr_app_type = curr_case.get("application_type")
    curr_coverage = float(curr_case.get("requested_coverage") or 0)
    
    # Parse findings for current medical condition and age
    curr_med_cond = ""
    curr_age = None
    if curr_case.get("findings"):
        try:
            findings = json.loads(curr_case["findings"]) if isinstance(curr_case["findings"], str) else curr_case["findings"]
            patient_details = findings.get("extracted_details", {}).get("patient_details", {})
            curr_med_cond = str(patient_details.get("medical_condition") or "").strip().lower()
            curr_age = patient_details.get("age")
            if curr_age is not None:
                curr_age = float(curr_age)
        except Exception as e:
            print(f"[calculate_past_cases_comparison Error parsing current case findings] {e}")
            
    # 2. Query completed historical cases (Approved / Rejected)
    completed_cases = fetch_all("""
        SELECT uc.id, uc.case_number, uc.applicant_name, uc.policy_type, uc.application_type, uc.requested_coverage, cs.status_name AS status, ra.findings
        FROM underwriting_cases uc
        JOIN case_statuses cs ON uc.status_id = cs.id
        LEFT JOIN risk_assessments ra ON ra.case_id = uc.id
        WHERE cs.status_name IN ('Approved', 'Rejected') AND uc.id != %s
    """, (case_id,))
    
    similar_cases = []
    
    for past in completed_cases:
        # Check basic categories
        past_policy = past.get("policy_type")
        past_app_type = past.get("application_type")
        past_coverage = float(past.get("requested_coverage") or 0)
        
        # Policy Type Match
        policy_match = (past_policy == curr_policy)
        policy_score = 0.25 if policy_match else 0.0
        policy_detail = f"Match ({past_policy})" if policy_match else f"Mismatch ({curr_policy or 'N/A'} vs {past_policy or 'N/A'})"
        
        # Application Type Match
        app_type_match = (past_app_type == curr_app_type)
        app_type_score = 0.15 if app_type_match else 0.0
        app_type_detail = f"Match ({past_app_type})" if app_type_match else f"Mismatch ({curr_app_type or 'N/A'} vs {past_app_type or 'N/A'})"
        
        # Parse past case findings
        past_med_cond = ""
        past_age = None
        if past.get("findings"):
            try:
                p_findings = json.loads(past["findings"]) if isinstance(past["findings"], str) else past["findings"]
                p_patient = p_findings.get("extracted_details", {}).get("patient_details", {})
                past_med_cond = str(p_patient.get("medical_condition") or "").strip().lower()
                past_age = p_patient.get("age")
                if past_age is not None:
                    past_age = float(past_age)
            except Exception as e:
                print(f"[calculate_past_cases_comparison Error parsing past case findings] {e}")
                
        # Calculate Medical Condition Similarity (+0.35)
        med_score = 0.0
        med_detail = ""
        if curr_med_cond and past_med_cond:
            # Simple text similarity: check word overlaps
            curr_words = set(re.findall(r'\w+', curr_med_cond))
            past_words = set(re.findall(r'\w+', past_med_cond))
            # Filter out generic stop words
            stops = {"none", "na", "n/a", "no", "major", "illness", "healthy", "and", "or", "disease", "history", "with"}
            curr_words = curr_words - stops
            past_words = past_words - stops
            
            if curr_words and past_words:
                overlap = curr_words.intersection(past_words)
                if overlap:
                    ratio = len(overlap) / max(len(curr_words), len(past_words))
                    med_score = round(0.35 * ratio, 2)
                    med_detail = f"Match: {', '.join(overlap)} ({int(ratio*100)}% overlap)"
                else:
                    med_detail = f"No common terms ({curr_med_cond} vs {past_med_cond})"
            elif not curr_words and not past_words:
                # Both are "No Major Illness" or equivalent
                med_score = 0.35
                med_detail = "Both No Major Illness"
        elif not curr_med_cond and not past_med_cond:
            med_score = 0.35
            med_detail = "Both No Major Illness"
        else:
            med_detail = f"Mismatch ({curr_med_cond or 'None'} vs {past_med_cond or 'None'})"
            
        # Calculate Age Proximity (+0.15)
        age_score = 0.0
        age_detail = ""
        if curr_age is not None and past_age is not None:
            age_diff = abs(curr_age - past_age)
            if age_diff <= 5:
                age_score = 0.15
            elif age_diff <= 10:
                age_score = 0.10
            elif age_diff <= 15:
                age_score = 0.05
            age_detail = f"Diff: {int(age_diff)} yrs ({int(curr_age)} vs {int(past_age)})"
        elif curr_age is None and past_age is None:
            age_score = 0.15
            age_detail = "Both missing age info"
        else:
            age_detail = f"Missing info ({curr_age or 'N/A'} vs {past_age or 'N/A'})"
            
        # Calculate Coverage Proximity (+0.10)
        cov_score = 0.0
        cov_detail = ""
        if curr_coverage > 0 and past_coverage > 0:
            cov_ratio = min(curr_coverage, past_coverage) / max(curr_coverage, past_coverage)
            if cov_ratio >= 0.7:  # within 30%
                cov_score = 0.10
            elif cov_ratio >= 0.5:  # within 50%
                cov_score = 0.05
            cov_detail = f"Ratio: {int(cov_ratio * 100)}% (${int(curr_coverage):,} vs ${int(past_coverage):,})"
        elif curr_coverage == 0 and past_coverage == 0:
            cov_score = 0.10
            cov_detail = "Both $0 coverage"
        else:
            cov_detail = f"Mismatch (${int(curr_coverage):,} vs ${int(past_coverage):,})"
            
        # Normalize score representation
        score = policy_score + app_type_score + med_score + age_score + cov_score
        score = round(score, 2)
        
        # Include as similar if score is >= 0.50
        if score >= 0.50:
            similar_cases.append({
                "case_id": past["id"],
                "case_number": past["case_number"],
                "applicant_name": past["applicant_name"],
                "status": past["status"],
                "policy_type": past_policy,
                "application_type": past_app_type,
                "requested_coverage": past_coverage,
                "medical_condition": past_med_cond.title() or "None",
                "similarity_score": int(score * 100),
                "similarity_breakdown": {
                    "policy_type": {"score": int(policy_score * 100), "detail": policy_detail, "max_score": 25},
                    "application_type": {"score": int(app_type_score * 100), "detail": app_type_detail, "max_score": 15},
                    "medical_condition": {"score": int(round(med_score * 100)), "detail": med_detail, "max_score": 35},
                    "age": {"score": int(age_score * 100), "detail": age_detail, "max_score": 15},
                    "coverage": {"score": int(cov_score * 100), "detail": cov_detail, "max_score": 10}
                }
            })
            
    # Sort similar cases by similarity score descending
    similar_cases.sort(key=lambda x: x["similarity_score"], reverse=True)
    
    # Calculate probabilities
    total = len(similar_cases)
    approved = sum(1 for c in similar_cases if c["status"].lower() == "approved")
    rejected = sum(1 for c in similar_cases if c["status"].lower() == "rejected")
    
    acceptance_prob = round((approved / total) * 100, 1) if total > 0 else 0.0
    rejection_prob = round((rejected / total) * 100, 1) if total > 0 else 0.0
    
    return {
        "acceptance_probability": acceptance_prob,
        "rejection_probability": rejection_prob,
        "compared_cases_count": total,
        "compared_cases": similar_cases[:10]  # Limit to top 10 similar cases
    }

def analyse_risk(case_id: int) -> dict:
    from database.connection import fetch_all, execute
    import re

    docs = fetch_all("SELECT d.file_name, oed.raw_text FROM ocr_extracted_data oed JOIN documents d ON oed.document_id = d.id WHERE d.case_id = %s", (case_id,))
    raw_text = "\n\n".join([f"--- SOURCE DOCUMENT: {doc['file_name']} ---\n{doc['raw_text']}" for doc in docs]) if docs else ""
    
    # Fix OCR artifact 'I' before numbers (e.g., 'I5,00,000' -> '5,00,000')
    import re
    raw_text = re.sub(r'(?<![a-zA-Z])I(\d{1,3}(?:,\d{2,3})*(?:\.\d+)?)', r'\1', raw_text)
    
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

    try:
        config_rows = fetch_all("SELECT parameter_category, condition_description, risk_weight FROM risk_score_config WHERE is_active = 1")
        import json
        config_json = json.dumps(config_rows)
    except Exception as e:
        print(f"[Config Fetch Error] {e}")
        config_json = "[]"

    llm_result = _call_llm(context_summary, kb_context, application_type, config_json)
    
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

    # Programmatic Confidence Score Calculation (Weighted Formula)
    # 1. Data Completeness (0.30 weight)
    completeness_fields = 0
    patient_details_extracted = python_extracted.get("patient_details", {})
    policy_details_extracted = python_extracted.get("policy_details", {})
    
    if patient_details_extracted.get("age"): completeness_fields += 1
    if patient_details_extracted.get("gender"): completeness_fields += 1
    if patient_details_extracted.get("medical_condition"): completeness_fields += 1
    if patient_details_extracted.get("bmi"): completeness_fields += 1
    if patient_details_extracted.get("blood_pressure"): completeness_fields += 1
    if patient_details_extracted.get("occupation"): completeness_fields += 1
    if patient_details_extracted.get("contact_number") or patient_details_extracted.get("email"): completeness_fields += 1
    if patient_details_extracted.get("aadhaar") or patient_details_extracted.get("pan"): completeness_fields += 1
    if policy_details_extracted.get("coverage_amount") or (case_rec[0].get("requested_coverage") if case_rec else None): completeness_fields += 1
    if docs: completeness_fields += 1
    
    completeness_score = completeness_fields / 10.0

    # 2. Data Reliability (0.25 weight)
    reliability_score = 1.0
    if fraud_detected:
        reliability_score -= 0.6
    if not docs:
        reliability_score -= 0.3
        
    neg_signals = llm_result.get("negative_signals", [])
    if isinstance(neg_signals, list) and len(neg_signals) > 0:
        reliability_score -= min(0.2, len(neg_signals) * 0.1)
        
    reliability_score = max(0.1, min(1.0, reliability_score))

    # 3. Guideline Match (0.30 weight)
    guideline_score = 1.0
    decision_str = str(decision).lower()
    if risk_level == "UNKNOWN" or "missing knowledge base guidelines" in decision_str:
        guideline_score = 0.1
    elif decision_str == "clarification required":
        guideline_score = 0.5
    else:
        # Check citations in breakdown
        has_citations = False
        llm_breakdown = llm_result.get("breakdown", [])
        if isinstance(llm_breakdown, list) and len(llm_breakdown) > 0:
            for b in llm_breakdown:
                if isinstance(b, dict) and b.get("citations") and len(b.get("citations")) > 0:
                    has_citations = True
                    break
        if not has_citations:
            guideline_score = 0.8

    # 4. Historical Similarity (0.15 weight)
    similarity_score = 0.0
    try:
        past_cases = calculate_past_cases_comparison(case_id)
        if past_cases.get("compared_cases_count", 0) > 0:
            compared_cases = past_cases.get("compared_cases", [])
            if compared_cases and len(compared_cases) > 0:
                similarity_score = compared_cases[0].get("similarity_score", 0.0) / 100.0
    except Exception as e:
        print(f"[risk_engine Confidence Calc - Similarity Error] {e}")

    # Calculate final confidence score
    calculated_confidence = (
        0.30 * completeness_score +
        0.25 * reliability_score +
        0.30 * guideline_score +
        0.15 * similarity_score
    )
    
    ai_confidence = max(0.40, min(0.98, calculated_confidence))

    extracted_details = llm_result.get("extracted_details", {}) if isinstance(llm_result, dict) else {}
    if not isinstance(extracted_details, dict): extracted_details = {}
    patient_details = extracted_details.get("patient_details", {}) if isinstance(extracted_details, dict) else {}
    policy_details = extracted_details.get("policy_details", {}) if isinstance(extracted_details, dict) else {}
    validity_dates = extracted_details.get("validity_dates", {}) if isinstance(extracted_details, dict) else {}

    safe_extracted_details = {
        "patient_details": {
            "age": (patient_details.get("age") if isinstance(patient_details, dict) else None) or patient.get("age"),
            "gender": (patient_details.get("gender") if isinstance(patient_details, dict) else None) or patient.get("gender"),
            "occupation": (patient_details.get("occupation") if isinstance(patient_details, dict) else None) or patient.get("occupation"),
            "marital_status": (patient_details.get("marital_status") if isinstance(patient_details, dict) else None) or patient.get("marital_status"),
            "contact_number": (patient_details.get("contact_number") if isinstance(patient_details, dict) else None) or patient.get("contact_number"),
            "email": (patient_details.get("email") if isinstance(patient_details, dict) else None) or patient.get("email"),
            "medical_condition": (patient_details.get("medical_condition") if isinstance(patient_details, dict) else None) or patient.get("medical_condition"),
            "bmi": (patient_details.get("bmi") if isinstance(patient_details, dict) else None) or patient.get("bmi"),
            "blood_pressure": (patient_details.get("blood_pressure") if isinstance(patient_details, dict) else None) or patient.get("blood_pressure"),
            "aadhaar": (patient_details.get("aadhaar") if isinstance(patient_details, dict) else None) or patient.get("aadhaar"),
            "pan": (patient_details.get("pan") if isinstance(patient_details, dict) else None) or patient.get("pan")
        },
        "policy_details": {
            "policy_number": (policy_details.get("policy_number") if isinstance(policy_details, dict) else None) or python_extracted.get("policy_details", {}).get("policy_number"),
            "policy_summary": (policy_details.get("policy_summary") if isinstance(policy_details, dict) else None) or python_extracted.get("policy_details", {}).get("policy_summary"),
            "coverage_amount": (policy_details.get("coverage_amount") if isinstance(policy_details, dict) else None) or python_extracted.get("policy_details", {}).get("coverage_amount"),
            "annual_premium": (policy_details.get("annual_premium") if isinstance(policy_details, dict) else None) or python_extracted.get("policy_details", {}).get("annual_premium"),
            "policy_term_years": (policy_details.get("policy_term_years") if isinstance(policy_details, dict) else None) or python_extracted.get("policy_details", {}).get("policy_term_years"),
            "nominee": (policy_details.get("nominee") if isinstance(policy_details, dict) else None) or python_extracted.get("policy_details", {}).get("nominee")
        },
        "validity_dates": {
            "from_date": (validity_dates.get("from_date") if isinstance(validity_dates, dict) else None) or python_extracted.get("validity_dates", {}).get("from_date"),
            "to_date": (validity_dates.get("to_date") if isinstance(validity_dates, dict) else None) or python_extracted.get("validity_dates", {}).get("to_date")
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
        "confidence_breakdown": {
            "completeness": completeness_score,
            "reliability": reliability_score,
            "guideline_match": guideline_score,
            "historical_similarity": similarity_score
        },
        "ai_flags": llm_result.get("negative_signals", []),
        "extracted_details": safe_extracted_details
    }
    return out
