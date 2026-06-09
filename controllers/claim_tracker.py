"""
Claim Tracker Controller API Router
Provides endpoints for unified customer search, CSV parser uploads,
dynamic API configurations, and local HTTP sandbox mock portals.
"""
import os
import json
import uuid
import traceback
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database.connection import execute, fetch_all, fetch_one
from utils.auth_deps import get_current_user
from services.claim_services import crawl_external_apis, parse_and_store_csv, cache_service, get_fallback_mock_data
from services.vector_store import query_rulebook_context, chroma_client, ef
from arango import ArangoClient

ARANGO_HOST     = os.getenv("ARANGO_URL")
ARANGO_DB       = os.getenv("ARANGO_DB")
ARANGO_USERNAME = os.getenv("ARANGO_USER")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD")

router = APIRouter(prefix="/claim-tracker", tags=["Claim Tracker"])

class ApiConfigCreate(BaseModel):
    company_name: str
    api_url: str
    api_key: str
    headers: Optional[str] = "{}"
    auth_type: str = "API Key"
    is_active: bool = True

def get_arango_patient_data(case_ids: list[int]) -> dict:
    if not case_ids:
        return {"nodes": [], "edges": []}
    try:
        client = ArangoClient(hosts=ARANGO_HOST)
        db = client.db(ARANGO_DB, username=ARANGO_USERNAME, password=ARANGO_PASSWORD)
        
        # Fetch entities
        ent_cursor = db.aql.execute(
            "FOR e IN entities FILTER e.case_id IN @case_ids RETURN e",
            bind_vars={"case_ids": case_ids}
        )
        entities = list(ent_cursor)
        
        # Fetch relationships
        rel_cursor = db.aql.execute(
            "FOR r IN relationships FILTER r.case_id IN @case_ids RETURN r",
            bind_vars={"case_ids": case_ids}
        )
        relationships = list(rel_cursor)
        
        return {
            "nodes": [
                {
                    "id": e["name"],
                    "label": e["label"],
                    "properties": e.get("properties", {})
                } for e in entities
            ],
            "edges": [
                {
                    "from_id": r["_from"].split("/")[-1].replace(f"case_{r['case_id']}_", "").replace("_", " "),
                    "to_id": r["_to"].split("/")[-1].replace(f"case_{r['case_id']}_", "").replace("_", " "),
                    "type": r["type"]
                } for r in relationships
            ]
        }
    except Exception as err:
        print(f"[Arango Query Warning] {err}")
        return {"nodes": [], "edges": []}

def get_chroma_patient_chunks(case_ids: list[int]) -> list:
    if not case_ids:
        return []
    try:
        dyn_collection = chroma_client.get_or_create_collection(
            name="underwriting_docs",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
        chunks = []
        for cid in case_ids:
            res = dyn_collection.get(where={"case_id": str(cid)})
            docs = res.get("documents", [])
            metas = res.get("metadatas", [])
            ids = res.get("ids", [])
            for doc, meta, doc_id in zip(docs, metas, ids):
                chunks.append({
                    "id": doc_id,
                    "text": doc,
                    "metadata": meta
                })
        return chunks
    except Exception as err:
        print(f"[Chroma Query Warning] {err}")
        return []

def get_risk_breakdown_for_claim(claim_id: str, risk_score: int) -> list:
    try:
        row = fetch_one("""
            SELECT ra.findings FROM risk_assessments ra
            JOIN underwriting_cases uc ON ra.case_id = uc.id
            WHERE uc.case_number = %s
        """, (claim_id,))
        if row and row.get("findings"):
            findings_data = json.loads(row["findings"])
            if "breakdown" in findings_data:
                return findings_data["breakdown"]
    except Exception as err:
        print(f"[get_risk_breakdown_for_claim Error] {err}")
        
    if risk_score <= 15:
        return [
            {"label": "Age Factor", "score": 0, "max_score": 80, "weight": 0.25, "justification": "Young applicant under 30 (0 pts)"},
            {"label": "BMI", "score": 0, "max_score": 70, "weight": 0.15, "justification": "Normal BMI (0 pts)"},
            {"label": "Disease History", "score": 0, "max_score": 80, "weight": 0.25, "justification": "No major declared conditions (0 pts)"},
            {"label": "Smoking & Alcohol", "score": 0, "max_score": 50, "weight": 0.15, "justification": "Non-smoker (0 pts)"},
            {"label": "Claim History", "score": 0, "max_score": 60, "weight": 0.10, "justification": "No history of claims (0 pts)"},
            {"label": "Lifestyle", "score": 0, "max_score": 50, "weight": 0.10, "justification": "Active lifestyle (0 pts)"}
        ]
    elif risk_score <= 30:
        return [
            {"label": "Age Factor", "score": 25, "max_score": 80, "weight": 0.25, "justification": "Age 31-45 (25 pts)"},
            {"label": "BMI", "score": 20, "max_score": 70, "weight": 0.15, "justification": "Slightly elevated BMI (20 pts)"},
            {"label": "Disease History", "score": 0, "max_score": 80, "weight": 0.25, "justification": "No major declared conditions (0 pts)"},
            {"label": "Smoking & Alcohol", "score": 10, "max_score": 50, "weight": 0.15, "justification": "Occasional smoker (10 pts)"},
            {"label": "Claim History", "score": 0, "max_score": 60, "weight": 0.10, "justification": "Clean history (0 pts)"},
            {"label": "Lifestyle", "score": 0, "max_score": 50, "weight": 0.10, "justification": "Active lifestyle (0 pts)"}
        ]
    else:
        return [
            {"label": "Age Factor", "score": 50, "max_score": 80, "weight": 0.25, "justification": "Age 46-60 (50 pts)"},
            {"label": "BMI", "score": 40, "max_score": 70, "weight": 0.15, "justification": "Obese BMI (40 pts)"},
            {"label": "Disease History", "score": 60, "max_score": 80, "weight": 0.25, "justification": "History of cardiovascular diseases (60 pts)"},
            {"label": "Smoking & Alcohol", "score": 50, "max_score": 50, "weight": 0.15, "justification": "Regular smoker (50 pts)"},
            {"label": "Claim History", "score": 60, "max_score": 60, "weight": 0.10, "justification": "Previous claim rejections (60 pts)"},
            {"label": "Lifestyle", "score": 30, "max_score": 50, "weight": 0.10, "justification": "Sedentary lifestyle (30 pts)"}
        ]

# ==========================================
# 1. SEARCH & MERGE CUSTOMER ENDPOINT
# ==========================================
@router.get("/search")
async def search_customer_claims(query: str, current_user: dict = Depends(get_current_user)):
    """
    Search customer history by Aadhaar, PAN, or Policy number.
    Merges:
      1. Internal DB Active Cases (via OCR text match)
      2. Internal DB Historical Claims (customer_claims table)
      3. Uploaded CSV records (uploaded_csv_records table)
      4. External Dynamic Company APIs (Tata AIG / HDFC / SBI / ICICI Lombard)
    Runs LLM RAG for consolidated fraud risk, similar claims, and recommendation.
    """
    clean_query = query.replace("-", "").replace(" ", "").strip()
    if not clean_query:
        raise HTTPException(status_code=400, detail="Search query cannot be empty.")

    # A. Check Redis/In-Memory Cache first
    cache_key = f"claim_profile_{clean_query}"
    cached_profile = cache_service.get(cache_key)
    if cached_profile:
        print(f"[Claim Tracker] Returning CACHED claims profile for: {clean_query}")
        return json.loads(cached_profile)

    print(f"[Claim Tracker] Cache miss. Initiating unified merge crawl for: {clean_query}")

    like_query = f"%{query.strip()}%"
    like_clean_query = f"%{clean_query}%"
    
    # Try to resolve a specific customer name from local database to help with queries
    customer_name = "Unknown Applicant"
    resolved_aadhaar = "N/A"
    resolved_pan = "N/A"
    
    if len(clean_query) == 12 and clean_query.isdigit():
        resolved_aadhaar = clean_query
    elif len(clean_query) == 10 and clean_query.isalnum():
        resolved_pan = clean_query.upper()
        
    try:
        name_row = fetch_one("""
            SELECT customer_name, aadhaar, pan FROM customer_claims 
            WHERE customer_name LIKE %s OR aadhaar = %s OR pan = %s OR policy_no = %s OR claim_id = %s
            LIMIT 1
        """, (like_query, clean_query, clean_query, clean_query, clean_query))
        
        if not name_row:
            name_row = fetch_one("""
                SELECT customer_name, aadhaar, pan FROM uploaded_csv_records 
                WHERE customer_name LIKE %s OR aadhaar = %s OR pan = %s
                LIMIT 1
            """, (like_query, clean_query, clean_query))
            
        if name_row:
            if name_row.get("customer_name"):
                customer_name = name_row["customer_name"]
            if name_row.get("aadhaar") and name_row["aadhaar"] != "N/A":
                resolved_aadhaar = name_row["aadhaar"]
            if name_row.get("pan") and name_row["pan"] != "N/A":
                resolved_pan = name_row["pan"]
    except Exception as name_err:
        print(f"[Claim Search] Failed to resolve name: {name_err}")

    if customer_name == "Unknown Applicant" and not clean_query.isdigit() and len(clean_query) > 2:
        customer_name = query.strip()

    # B. Fetch from 1: Internal Database (Active Underwriting Cases)
    internal_cases = []
    internal_case_docs = []
    case_ids = []
    risk_score = 0
    risk_findings = {}

    try:
        # Search OCR text for matching query
        ocr_matches = fetch_all("""
            SELECT DISTINCT document_id FROM ocr_extracted_data 
            WHERE raw_text LIKE %s
        """, (like_clean_query,))
        
        doc_ids = [m["document_id"] for m in ocr_matches]
        
        # Build query for cases matching name, case number, or documents
        sql_cases = """
            SELECT DISTINCT uc.id, uc.case_number, uc.applicant_name, uc.policy_type, uc.requested_coverage, uc.underwriter_remarks, uc.created_at, uc.document_errors, cs.status_name AS status,
                            uc.priority, uc.sla_due_at, uc.existing_policy_details
            FROM underwriting_cases uc
            LEFT JOIN case_statuses cs ON uc.status_id = cs.id
            LEFT JOIN documents d ON d.case_id = uc.id
            WHERE uc.applicant_name LIKE %s 
               OR uc.case_number LIKE %s
        """
        params_cases = [like_query, like_clean_query]
        
        if doc_ids:
            placeholders = ",".join(["%s"] * len(doc_ids))
            sql_cases += f" OR d.id IN ({placeholders})"
            params_cases.extend(doc_ids)
            
        case_rows = fetch_all(sql_cases, params_cases)
        case_ids = [r["id"] for r in case_rows]
        
        for r in case_rows:
            if customer_name == "Unknown Applicant":
                customer_name = r["applicant_name"]
                
            # Fetch risk assessments
            risk_row = fetch_one("SELECT risk_score, risk_level, findings FROM risk_assessments WHERE case_id = %s", (r["id"],))
            r_score = risk_row["risk_score"] if risk_row else 0
            risk_score = max(risk_score, r_score)
            
            if risk_row and risk_row["findings"]:
                try:
                    risk_findings = json.loads(risk_row["findings"]) if isinstance(risk_row["findings"], str) else risk_row["findings"]
                except Exception:
                    pass

            # Fetch documents
            docs = fetch_all("SELECT file_name FROM documents WHERE case_id = %s", (r["id"],))
            doc_names = ", ".join(d["file_name"] for d in docs)
            
            # Fetch case underwriting decisions from underwriting_decisions
            decisions = fetch_all("""
                SELECT ud.decision, ud.remarks, ud.created_at, u.username
                FROM underwriting_decisions ud
                LEFT JOIN users u ON ud.user_id = u.id
                WHERE ud.case_id = %s
                ORDER BY ud.created_at DESC
            """, (r["id"],))
            
            # Fetch document errors and verification status along with OCR text
            case_docs = fetch_all("""
                SELECT d.file_name, d.file_path, d.document_type_id, d.verification_status,
                       o.raw_text, o.structured_data
                FROM documents d
                LEFT JOIN ocr_extracted_data o ON d.id = o.document_id
                WHERE d.case_id = %s
            """, (r["id"],))
            for cd in case_docs:
                internal_case_docs.append({
                    "file_name": cd["file_name"],
                    "file_path": cd["file_path"],
                    "verification_status": cd["verification_status"] or "Pending",
                    "doc_type": "Identity Proof" if cd["document_type_id"] == 3 else "Discharge Summary" if cd["document_type_id"] == 2 else "Claim Form" if cd["document_type_id"] == 1 else "Other",
                    "raw_text": cd["raw_text"],
                    "structured_data": cd["structured_data"]
                })
            
            internal_cases.append({
                "claim_id": f"CASE-{r['case_number']}",
                "company": "Internal Insurance DB",
                "policy_no": r["case_number"],
                "claim_date": r["created_at"].strftime('%Y-%m-%d') if r["created_at"] else "",
                "amount": float(r["requested_coverage"]) if r["requested_coverage"] else 0.0,
                "status": r["status"] or "Under Review",
                "risk_score": r_score,
                "risk_flags": "Active Underwriting Application",
                "documents": doc_names,
                "disease": risk_findings.get("extracted_details", {}).get("patient_details", {}).get("medical_condition", "Declared"),
                "hospital": "N/A",
                "document_errors": json.loads(r["document_errors"]) if r.get("document_errors") else None,
                "priority": r.get("priority") or "Medium",
                "sla_due_at": r["sla_due_at"].strftime('%Y-%m-%d %H:%M:%S') if r.get("sla_due_at") else "",
                "existing_policy_details": r.get("existing_policy_details") or "None",
                "decisions": [
                    {
                        "decision": d["decision"],
                        "remarks": d["remarks"],
                        "created_at": d["created_at"].strftime('%Y-%m-%d %H:%M:%S') if d["created_at"] else "",
                        "username": d["username"] or "System"
                    }
                    for d in decisions
                ]
            })
    except Exception as db_err:
        print(f"[Claim Search] Internal DB search failed: {db_err}")

# C. Fetch from 2: Internal Database Claims Ledger (customer_claims table)
    internal_ledger_claims = []
    try:
        ledger_rows = fetch_all("""
            SELECT * FROM customer_claims 
            WHERE customer_name LIKE %s 
               OR aadhaar = %s 
               OR pan = %s 
               OR policy_no LIKE %s 
               OR claim_id LIKE %s
        """, (like_query, clean_query, clean_query, like_clean_query, like_clean_query))
        
        for r in ledger_rows:
            if customer_name == "Unknown Applicant":
                customer_name = r["customer_name"]
            
            # Fetch underwriting decisions if this is linked to a case in underwriting_cases
            linked_case = fetch_one("SELECT id FROM underwriting_cases WHERE case_number = %s", (r["policy_no"],))
            decisions = []
            doc_errors = None
            if linked_case:
                decisions = fetch_all("""
                    SELECT ud.decision, ud.remarks, ud.created_at, u.username
                    FROM underwriting_decisions ud
                    LEFT JOIN users u ON ud.user_id = u.id
                    WHERE ud.case_id = %s
                    ORDER BY ud.created_at DESC
                """, (linked_case["id"],))
                
                case_info = fetch_one("SELECT document_errors FROM underwriting_cases WHERE id = %s", (linked_case["id"],))
                if case_info and case_info.get("document_errors"):
                    doc_errors = json.loads(case_info["document_errors"])

            internal_ledger_claims.append({
                "claim_id": r["claim_id"],
                "company": r["company"],
                "policy_no": r["policy_no"],
                "claim_date": r["created_at"].strftime('%Y-%m-%d') if r["created_at"] else "",
                "amount": float(r["amount"]),
                "status": r["status"],
                "risk_score": r["risk_score"],
                "risk_flags": "None" if r["risk_score"] < 40 else "Medium Risk Claims" if r["risk_score"] < 60 else "High Claim History Risk",
                "documents": r["documents"] or "",
                "disease": "Historical Record",
                "hospital": "N/A",
                "document_errors": doc_errors,
                "decisions": [
                    {
                        "decision": d["decision"],
                        "remarks": d["remarks"],
                        "created_at": d["created_at"].strftime('%Y-%m-%d %H:%M:%S') if d["created_at"] else "",
                        "username": d["username"] or "System"
                    }
                    for d in decisions
                ]
            })
            # Harvest details
            for doc in (r["documents"] or "").split(","):
                if doc.strip():
                    internal_case_docs.append({
                        "file_name": doc.strip(),
                        "file_path": "INTERNAL_DB",
                        "verification_status": "Verified",
                        "doc_type": "Discharge Summary" if "discharge" in doc.lower() else "Identity Proof" if "identity" in doc.lower() or "aadhaar" in doc.lower() else "Hospital Bills" if "bill" in doc.lower() else "Other"
                    })
    except Exception as ledger_err:
        print(f"[Claim Search] Historical ledger search failed: {ledger_err}")

    # D. Fetch from 3: Uploaded CSV records table
    csv_claims = []
    try:
        csv_rows = fetch_all("""
            SELECT * FROM uploaded_csv_records 
            WHERE customer_name LIKE %s 
               OR aadhaar = %s 
               OR pan = %s 
               OR claim_history LIKE %s
        """, (like_query, clean_query, clean_query, like_clean_query))
        
        for r in csv_rows:
            if r["customer_name"]:
                customer_name = r["customer_name"]
            
            hist = []
            if r["claim_history"]:
                hist = json.loads(r["claim_history"]) if isinstance(r["claim_history"], str) else r["claim_history"]
                
            for c in hist:
                csv_claims.append({
                    "claim_id": c.get("claim_id", f"CSV-{uuid.uuid4().hex[:6].upper()}"),
                    "company": c.get("company", "CSV Record"),
                    "policy_no": c.get("policy_no", "CSV-POL"),
                    "claim_date": c.get("claim_date", datetime.now().strftime('%Y-%m-%d')),
                    "amount": float(c.get("amount", c.get("claim_amount", 0.0))),
                    "status": c.get("status", "Approved"),
                    "risk_score": int(c.get("risk_score", 15)),
                    "risk_flags": r["risk_flags"] or "CSV Imported Record",
                    "documents": r["documents"] or "",
                    "disease": c.get("disease", c.get("claim_details", "CSV Claim")),
                    "hospital": c.get("hospital", "CSV Clinic"),
                    "document_errors": None,
                    "decisions": []
                })
                
            for doc in (r["documents"] or "").split(","):
                if doc.strip():
                    internal_case_docs.append({
                        "file_name": doc.strip(),
                        "file_path": "CSV_RECORD",
                        "verification_status": "Verified",
                        "doc_type": "Discharge Summary" if "discharge" in doc.lower() else "Identity Proof" if "identity" in doc.lower() or "aadhaar" in doc.lower() else "Hospital Bills" if "bill" in doc.lower() else "Other"
                    })
    except Exception as csv_err:
        print(f"[Claim Search] CSV search failed: {csv_err}")

    # E. Fetch from 4: External Company APIs (Tata AIG / HDFC / SBI / ICICI Lombard)
    external_claims = []
    
    # Classify clean query for external API parameter mapping
    aadhaar_query = None
    pan_query = None
    policy_query = None
    
    if len(clean_query) == 12 and clean_query.isdigit():
        aadhaar_query = clean_query
    elif len(clean_query) == 10 and clean_query.isalnum():
        pan_query = clean_query.upper()
    else:
        policy_query = query.strip() # Pass original query to mock resolver so it can match by name/policy
        
    try:
        external_claims = await crawl_external_apis(
            aadhaar=aadhaar_query,
            pan=pan_query,
            policy_no=policy_query
        )
        for ec in external_claims:
            for doc in ec.get("documents", "").split(","):
                if doc.strip():
                    internal_case_docs.append({
                        "file_name": doc.strip(),
                        "file_path": f"EXTERNAL_API_{ec.get('company')}",
                        "verification_status": "Verified",
                        "doc_type": "Discharge Summary" if "discharge" in doc.lower() else "Identity Proof" if "identity" in doc.lower() or "aadhaar" in doc.lower() else "Hospital Bills" if "bill" in doc.lower() else "Other"
                    })
    except Exception as crawl_err:
        print(f"[Claim Search] Async API crawl failed: {crawl_err}")

    # F. Merge & Deduplicate all Claims History
    merged_claims = []
    seen_claim_ids = set()
    
    for c in (internal_cases + internal_ledger_claims + csv_claims + external_claims):
        cid = c["claim_id"]
        if cid not in seen_claim_ids:
            c["risk_breakdown"] = get_risk_breakdown_for_claim(c["claim_id"], c.get("risk_score", 15))
            c["customer_name"] = customer_name
            c["aadhaar"] = resolved_aadhaar
            c["pan"] = resolved_pan
            merged_claims.append(c)
            seen_claim_ids.add(cid)
            
    # Calculate deterministic base metrics
    total_amount = sum(c["amount"] for c in merged_claims)
    rejected_count = sum(1 for c in merged_claims if c["status"].lower() in ["rejected", "denied"])
    approved_count = sum(1 for c in merged_claims if c["status"].lower() == "approved")
    
    # Heuristic average risk score
    raw_scores = [c["risk_score"] for c in merged_claims if c.get("risk_score")]
    blended_risk = round(sum(raw_scores) / len(raw_scores), 1) if raw_scores else 15.0
    
    # Risk Dial & Fraud Probability Engine
    fraud_prob = 10.0 # Base minimum
    if rejected_count > 0:
        fraud_prob += (25.0 * rejected_count)
    if blended_risk > 50:
        fraud_prob += 20.0
    # Search flags
    for c in merged_claims:
        flags = str(c.get("risk_flags", "")).lower()
        if "suspicious" in flags or "inflation" in flags or "fraud" in flags:
            fraud_prob += 35.0
            
    fraud_prob = min(99.0, max(5.0, fraud_prob))

    # G. AI Analytics Flow: ChromaDB RAG Guidelines + Relationship summaries
    underwriting_rules = "Standard underwriting guidelines: claim ratios > 1.0 are critical. Fraud indicators include multiple rejected claims."
    try:
        # Fetch relevant rules context from rulebooks ChromaDB collection
        rules_list = query_rulebook_context(query="Health insurance rules for fraud detection and pre-existing disease claims history", n_results=2)
        if rules_list:
            underwriting_rules = "\n".join(rules_list)
    except Exception as rag_err:
        print(f"[Claim Search] ChromaDB rulebooks query failed: {rag_err}")

    # H. Execute Mistral LLM to compile actuarial narrative and audit report
    ai_narrative = "No Mistral AI configuration active. Using deterministic actuarial rules."
    underwriting_recommendation = "Standard Underwriter Review Required."
    risk_factors = []
    pos_signals = []
    neg_signals = []
    similar_claims = []

    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    if MISTRAL_API_KEY and MISTRAL_API_KEY != "your_mistral_key_here":
        try:
            from mistralai.client import MistralClient
            from mistralai.models.chat_completion import ChatMessage
            
            prompt = f"""You are a Principal Health Actuary and Lead Claims Investigator at SBI General Insurance.
Analyze the following merged claim history for customer "{customer_name}" (Aadhaar/PAN: {clean_query}):

MERGED CLAIMS LEDGER:
{json.dumps(merged_claims, indent=2)}

SBI UNDERWRITING RULES & RAG CONTEXT:
{underwriting_rules}

Generate a comprehensive risk summary and fraud audit report. 
Strictly respond with a JSON object in this exact format (no markdown wrappers, no introductory chat):
{{
  "risk_summary": "detailed 3-4 sentence professional underwriter analysis of the customer claim history",
  "fraud_probability": {fraud_prob},
  "underwriting_recommendation": "Approve / Decline / Refer to Senior Underwriter with justification",
  "risk_factors": ["key risk factor 1", "key risk factor 2"],
  "positive_signals": ["positive signal 1", "positive signal 2"],
  "negative_signals": ["negative claim flag 1", "negative claim flag 2"],
  "similar_claims": [
    {{
      "claim_id": "CLM-XXXX",
      "similarity_reason": "why this claim is similar to others, e.g. same disease Gastritis, same hospital Fortis"
    }}
  ]
}}
"""
            kwargs = {"api_key": MISTRAL_API_KEY, "timeout": 120}
            if os.getenv("MISTRAL_MODE") == "Local":
                kwargs["endpoint"] = os.getenv("MISTRAL_LOCAL_URL")
            client = MistralClient(**kwargs)
            response = client.chat(
                model="mistral-tiny", 
                messages=[ChatMessage(role="user", content=prompt)],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            raw_ai = response.choices[0].message.content
            import re
            cleaned_ai = re.sub(r'^```json\s*|\s*```$', '', raw_ai.strip())
            ai_data = json.loads(cleaned_ai)
            
            ai_narrative = ai_data.get("risk_summary", ai_narrative)
            underwriting_recommendation = ai_data.get("underwriting_recommendation", underwriting_recommendation)
            risk_factors = ai_data.get("risk_factors", [])
            pos_signals = ai_data.get("positive_signals", [])
            neg_signals = ai_data.get("negative_signals", [])
            similar_claims = ai_data.get("similar_claims", [])
            fraud_prob = ai_data.get("fraud_probability", fraud_prob)
            
        except Exception as ai_err:
            print(f"[Claim Search] LLM analysis failed: {ai_err}")

    # Fallback details if AI is bypass
    if not risk_factors:
        if total_amount > 200000:
            risk_factors.append("High claim volume: Exceeds ₹2 Lakhs in total exposure.")
        if rejected_count > 0:
            risk_factors.append(f"Contains {rejected_count} rejected claims in historical records.")
            neg_signals.append("History of claims rejection.")
        else:
            pos_signals.append("Clean claim fulfillment ratio.")

    # Separately categorize merged_claims into previous and current list summaries
    prev_list = []
    curr_list = []
    for c in merged_claims:
        cid = c.get("claim_id", "")
        comp = c.get("company", "")
        amt = float(c.get("amount", 0.0))
        stat = c.get("status", "")
        
        amt_str = f"₹{int(amt)}"
        if amt >= 100000:
            amt_str = f"₹{round(amt/100000, 2)}L"
        elif amt >= 1000:
            amt_str = f"₹{round(amt/1000, 1)}k"
            
        desc = f"{cid} ({comp}): {stat} ({amt_str})"
        if cid.startswith("CASE-"):
            curr_list.append(desc)
        else:
            prev_list.append(desc)
            
    prev_summary = "; ".join(prev_list) if prev_list else "None"
    curr_summary = "; ".join(curr_list) if curr_list else "None"
    
    # Store summaries on all claims in list so the UI columns show them
    for c in merged_claims:
        c["previous_claims"] = prev_summary
        c["current_claims"] = curr_summary

    # Query ArangoDB (Aurango Graph DB)
    arango_res = get_arango_patient_data(case_ids)

    # Query ChromaDB (Vector DB)
    chroma_res = get_chroma_patient_chunks(case_ids)

    # Deduplicate document files list and enrich with OCR raw text
    deduplicated_docs = []
    seen_docs = set()
    for d in internal_case_docs:
        if d["file_name"] not in seen_docs:
            ocr_row = None
            try:
                ocr_row = fetch_one("""
                    SELECT raw_text, structured_data FROM ocr_extracted_data o
                    JOIN documents d ON o.document_id = d.id
                    WHERE d.file_name = %s
                """, (d["file_name"],))
            except Exception as ocr_err:
                print(f"[OCR DB Lookup Error] {ocr_err}")
                
            d["raw_text"] = ocr_row["raw_text"] if ocr_row else None
            d["structured_data"] = ocr_row["structured_data"] if ocr_row else None
            deduplicated_docs.append(d)
            seen_docs.add(d["file_name"])

    # I. Build final payload
    payload = {
        "customer_details": {
            "name": customer_name,
            "aadhaar": resolved_aadhaar,
            "pan": resolved_pan,
            "policy_no": policy_query or "N/A",
            "risk_score": blended_risk,
            "fraud_probability": fraud_prob,
            "total_amount": total_amount,
            "claims_count": len(merged_claims),
            "approved_count": approved_count,
            "rejected_count": rejected_count,
            "previous_claims": prev_summary,
            "current_claims": curr_summary
        },
        "claims_history": merged_claims,
        "documents": deduplicated_docs,
        "arango_data": arango_res,
        "chroma_data": chroma_res,
        "case_ids": case_ids,
        "ai_features": {
            "risk_summary": ai_narrative,
            "fraud_probability": fraud_prob,
            "similar_claims": similar_claims,
            "underwriting_recommendation": underwriting_recommendation,
            "risk_factors": risk_factors,
            "positive_signals": pos_signals,
            "negative_signals": neg_signals
        }
    }

    # J. Save in cache for 5 minutes
    try:
        cache_service.set(cache_key, json.dumps(payload), expire_seconds=300)
    except Exception as cache_err:
        print(f"[Claim Tracker] Failed to write key to cache: {cache_err}")

    return payload


# ==========================================
# 1.5 FETCH ALL CUSTOMER CLAIMS ENDPOINT
# ==========================================
@router.get("/all")
async def get_all_customer_claims(limit: int = 100, current_user: dict = Depends(get_current_user)):
    """
    Fetch all customer claims from the customer_claims table.
    """
    try:
        claims = fetch_all("""
            SELECT id, customer_name, aadhaar, pan, policy_no, claim_id, company, amount, status, risk_score, documents, created_at, 'None' AS assigned_user
            FROM customer_claims
            UNION ALL
            SELECT uc.id, uc.applicant_name AS customer_name, 'N/A' AS aadhaar, 'N/A' AS pan, 
                   uc.case_number AS policy_no, CONCAT('CASE-', uc.case_number) AS claim_id, 
                   'Internal Insurance DB' AS company, uc.requested_coverage AS amount, 
                   cs.status_name AS status, 0 AS risk_score, '' AS documents, uc.created_at,
                   COALESCE((SELECT full_name FROM users WHERE id = uc.assigned_to), (SELECT username FROM users WHERE id = uc.assigned_to), 'None') AS assigned_user
            FROM underwriting_cases uc
            JOIN case_statuses cs ON uc.status_id = cs.id
            WHERE cs.status_name IN ('Approved', 'Rejected', 'Referred')
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        
        # Serialize datetime and decimals, and populate previous_claims/current_claims summaries
        for claim in claims:
            if claim.get("created_at"):
                claim["created_at"] = claim["created_at"].strftime('%Y-%m-%d %H:%M:%S')
            claim["amount"] = float(claim["amount"]) if claim.get("amount") is not None else 0.0
            claim["risk_breakdown"] = get_risk_breakdown_for_claim(claim["claim_id"], claim["risk_score"])
            
            # Find all matching claims for this customer using Aadhaar, PAN or Customer Name
            aadhaar = claim.get("aadhaar")
            pan = claim.get("pan")
            customer_name = claim.get("customer_name")
            
            where_clauses = []
            params = []
            if aadhaar and aadhaar != "N/A":
                where_clauses.append("aadhaar = %s")
                params.append(aadhaar)
            if pan and pan != "N/A":
                where_clauses.append("pan = %s")
                params.append(pan)
            
            if not where_clauses:
                where_clauses.append("customer_name = %s")
                params.append(customer_name)
                
            sql_other = f"""
                SELECT claim_id, company, amount, status 
                FROM customer_claims 
                WHERE {" OR ".join(where_clauses)}
            """
            try:
                other_claims = fetch_all(sql_other, tuple(params))
                previous_list = []
                current_list = []
                for oc in other_claims:
                    cid = oc["claim_id"]
                    comp = oc["company"]
                    amt = float(oc["amount"])
                    stat = oc["status"]
                    
                    amt_str = f"₹{int(amt)}"
                    if amt >= 100000:
                        amt_str = f"₹{round(amt/100000, 2)}L"
                    elif amt >= 1000:
                        amt_str = f"₹{round(amt/1000, 1)}k"
                    
                    desc = f"{cid} ({comp}): {stat} ({amt_str})"
                    if cid.startswith("CASE-"):
                        current_list.append(desc)
                    else:
                        previous_list.append(desc)
                        
                claim["previous_claims"] = "; ".join(previous_list) if previous_list else "None"
                claim["current_claims"] = "; ".join(current_list) if current_list else "None"
            except Exception as other_err:
                print(f"[claim_tracker all] Failed to query other claims: {other_err}")
                claim["previous_claims"] = "None"
                claim["current_claims"] = "None"
            
        return claims
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch customer claims: {str(e)}")



# ==========================================
# 2. CSV FILE INGESTION ENDPOINT
# ==========================================
@router.post("/admin/upload-csv")
async def admin_upload_claims_csv(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Ingests historical claims CSV into MySQL uploaded_csv_records table."""
    # Ensure Brokers (role_id=5) are not allowed to upload claims CSV logs
    if current_user["role_id"] == 5:
        raise HTTPException(status_code=403, detail="Brokers are not authorized to upload claims CSV logs.")
        
    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".csv":
        raise HTTPException(status_code=400, detail="Only CSV files (.csv) are accepted.")
        
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"claims_ingest_{uuid.uuid4().hex[:6]}.csv")
    
    try:
        content = await file.read()
        with open(temp_path, "wb") as f:
            f.write(content)
            
        # Parse CSV
        result = parse_and_store_csv(temp_path)
        
        # Log to Audit Logs
        from services.audit_service import log_action
        log_action(current_user["user_id"], "CSV_CLAIMS_INGESTION", {
            "file_name": file.filename,
            "records_inserted": result["inserted"],
            "errors_count": len(result["errors"])
        })
        
        # Clean file from disk
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        return {
            "message": "CSV Ingestion complete",
            "records_inserted": result["inserted"],
            "errors": result["errors"]
        }
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise HTTPException(status_code=500, detail=f"CSV ingestion failed: {str(e)}")



# ==========================================
# 4. LOCAL SANDBOX HTTP MOCK APIs
# ==========================================
@router.get("/mock-api/tata-aig")
async def mock_tata_aig_api(aadhaar: Optional[str] = None, pan: Optional[str] = None, policy_no: Optional[str] = None):
    """Local dynamic sandbox endpoint simulating Tata AIG claims portal."""
    query_val = aadhaar or pan or policy_no or ""
    return get_fallback_mock_data("Tata AIG", "", query_val)

@router.get("/mock-api/hdfc")
async def mock_hdfc_api(aadhaar: Optional[str] = None, pan: Optional[str] = None, policy_no: Optional[str] = None):
    """Local dynamic sandbox endpoint simulating HDFC ERGO claims portal."""
    query_val = aadhaar or pan or policy_no or ""
    return get_fallback_mock_data("HDFC ERGO", "", query_val)

@router.get("/mock-api/sbi")
async def mock_sbi_api(aadhaar: Optional[str] = None, pan: Optional[str] = None, policy_no: Optional[str] = None):
    """Local dynamic sandbox endpoint simulating SBI General claims portal."""
    query_val = aadhaar or pan or policy_no or ""
    return get_fallback_mock_data("SBI General", "", query_val)

@router.get("/mock-api/icici")
async def mock_icici_api(aadhaar: Optional[str] = None, pan: Optional[str] = None, policy_no: Optional[str] = None):
    """Local dynamic sandbox endpoint simulating ICICI Lombard claims portal."""
    query_val = aadhaar or pan or policy_no or ""
    return get_fallback_mock_data("ICICI Lombard", "", query_val)
