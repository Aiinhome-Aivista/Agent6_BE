from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database.connection import execute, fetch_all, fetch_one
from utils.auth_deps import get_current_user
import uuid
import os
import json

router = APIRouter(prefix="/cases", tags=["Cases"])

from typing import Optional

class CaseCreate(BaseModel):
    applicant_name: str
    policy_type: str
    product_type: str = "Standard"
    priority: str = "Medium"
    existing_policy_details: Optional[str] = None
    requested_coverage: Optional[float] = None
    application_type: str = "Existing Claim"

@router.post("/")
async def create_case(case: CaseCreate, current_user: dict = Depends(get_current_user)):
    """Creates a new underwriting case. Requires Agent/Broker persona (role_id=5) or Admin."""
    if current_user["role_id"] not in [5, 1]:
        raise HTTPException(status_code=403, detail="Only Agents/Brokers can submit new cases.")

    case_number = f"CASE-{uuid.uuid4().hex[:8].upper()}"
    
    # Calculate SLA based on configuration
    from datetime import datetime, timedelta
    config_row = fetch_one("SELECT config_value FROM system_config WHERE config_key = 'SLA_DAYS'")
    max_days = int(config_row["config_value"]) if config_row else 5
    sla_due_at = datetime.now() + timedelta(days=max_days)
    
    # Auto-assign to an underwriter (role_id = 4) with the least number of active cases
    assignee_row = fetch_one("""
        SELECT u.id 
        FROM users u 
        LEFT JOIN underwriting_cases uc ON u.id = uc.assigned_to AND uc.status_id IN (1, 2) 
        WHERE u.role_id = 4 AND u.is_active = 1
        GROUP BY u.id 
        ORDER BY COUNT(uc.id) ASC 
        LIMIT 1
    """)
    assigned_to = assignee_row["id"] if assignee_row else None

    sql = """
        INSERT INTO underwriting_cases (case_number, applicant_name, policy_type, product_type_id, existing_policy_details, requested_coverage, priority, sla_due_at, status_id, user_id, application_type, assigned_to)
        VALUES (%s, %s, %s, COALESCE((SELECT id FROM product_types WHERE product_name = %s), 1), %s, %s, %s, %s, (SELECT id FROM case_statuses WHERE status_name = 'Submitted'), %s, %s, %s)
    """
    try:
        case_id = execute(sql, (
            case_number, case.applicant_name, case.policy_type, case.product_type,
            case.existing_policy_details, case.requested_coverage, 
            case.priority, sla_due_at.strftime('%Y-%m-%d %H:%M:%S'),
            current_user["user_id"], case.application_type, assigned_to
        ))
        return {"message": "Case submitted successfully", "case_id": case_id, "case_number": case_number}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

class CaseUpdate(BaseModel):
    applicant_name: str
    policy_type: str
    product_type: str = "Standard"
    priority: str = "Medium"
    existing_policy_details: Optional[str] = None
    requested_coverage: Optional[float] = None

@router.put("/{case_id}")
async def update_case(case_id: int, case: CaseUpdate, current_user: dict = Depends(get_current_user)):
    """Updates an existing case details and resets status to pending."""
    if current_user["role_id"] not in [5, 1]:
        raise HTTPException(status_code=403, detail="Not authorized.")
    # Calculate SLA based on configuration
    from datetime import datetime, timedelta
    config_row = fetch_one("SELECT config_value FROM system_config WHERE config_key = 'SLA_DAYS'")
    max_days = int(config_row["config_value"]) if config_row else 5
    sla_due_at = datetime.now() + timedelta(days=max_days)

    sql = """
        UPDATE underwriting_cases 
        SET applicant_name=%s, policy_type=%s, product_type_id=COALESCE((SELECT id FROM product_types WHERE product_name = %s), 1), existing_policy_details=%s, requested_coverage=%s, priority=%s, sla_due_at=%s, status_id=(SELECT id FROM case_statuses WHERE status_name = 'Submitted')
        WHERE id=%s AND user_id=%s
    """
    execute(sql, (case.applicant_name, case.policy_type, case.product_type, case.existing_policy_details, case.requested_coverage, case.priority, sla_due_at.strftime('%Y-%m-%d %H:%M:%S'), case_id, current_user["user_id"]))
    return {"message": "Case updated successfully"}

@router.get("/{case_id}/documents")
async def get_case_documents(case_id: int, current_user: dict = Depends(get_current_user)):
    """Fetches list of documents uploaded for a case."""
    docs = fetch_all("SELECT id, file_name, created_at FROM documents WHERE case_id = %s ORDER BY created_at DESC", (case_id,))
    return docs

@router.delete("/{case_id}/documents/{doc_id}")
async def delete_case_document(case_id: int, doc_id: int, current_user: dict = Depends(get_current_user)):
    """Deletes a specific document from a case."""
    if current_user["role_id"] not in [5, 1]:
        raise HTTPException(status_code=403, detail="Not authorized to delete documents.")
        
    doc = fetch_one("SELECT file_path FROM documents WHERE id = %s AND case_id = %s", (doc_id, case_id))
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
        
    try:
        # Delete file from disk
        if os.path.exists(doc["file_path"]) and doc["file_path"] != "API_DIRECT_TEXT":
            os.remove(doc["file_path"])
            
        # Delete from dependent tables first
        execute("DELETE FROM ocr_extracted_data WHERE document_id = %s", (doc_id,))
        
        # Delete from DB
        execute("DELETE FROM documents WHERE id = %s AND case_id = %s", (doc_id, case_id))
        return {"message": "Document deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/")
async def get_cases(current_user: dict = Depends(get_current_user)):
    """Fetches cases. Brokers only see their own. Underwriters/Admins see all."""
    role_id = current_user["role_id"]
    user_id = current_user["user_id"]

    sql = """SELECT uc.id, uc.case_number, uc.applicant_name, uc.policy_type, uc.application_type, pt.product_name AS product_type, uc.requested_coverage, uc.existing_policy_details, cs.status_name AS status, uc.priority, uc.sla_due_at, uc.created_at, uc.company_name, uc.product_name, uc.underwriter_remarks, uc.user_id, uc.assigned_to,
             (SELECT COALESCE(full_name, username) FROM users WHERE id = uc.assigned_to) AS assigned_user,
             (SELECT role_id FROM case_mail_log cml WHERE cml.case_id = uc.id AND cml.is_escalated = 0 AND cml.action_taken = 0 ORDER BY cml.id DESC LIMIT 1) AS current_role_id
             FROM underwriting_cases uc 
             LEFT JOIN case_statuses cs ON uc.status_id = cs.id
             LEFT JOIN product_types pt ON uc.product_type_id = pt.id
             WHERE (cs.status_name IS NULL OR cs.status_name NOT IN ('Approved', 'Rejected'))"""
    
    params = []
    
    if role_id == 5:
        # Brokers see only their own cases
        sql += " AND uc.user_id = %s"
        params.append(user_id)
    elif role_id in [3, 4]:
        # Underwriters and Managers see unassigned cases or cases specifically assigned to them
        sql += " AND (uc.assigned_to IS NULL OR uc.assigned_to = %s)"
        params.append(user_id)

    sql += " ORDER BY uc.created_at DESC"

    try:
        return fetch_all(sql, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from fastapi import Form

@router.post("/check_documents")
async def check_documents(
    files: list[UploadFile] = File(...), 
    application_type: str = Form("Existing Claim"),
    current_user: dict = Depends(get_current_user)
):
    """Checks uploaded documents for missing required documents using LLM."""
    if current_user["role_id"] not in [5, 1]:
        raise HTTPException(status_code=403, detail="Only Agents/Brokers can upload documents.")

    import os
    import json
    import uuid
    from services.ocr_service import extract_text
    
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    
    combined_text = ""
    temp_files = []
    
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        unique_name = f"temp_check_{uuid.uuid4().hex[:6]}{ext}"
        file_path = os.path.join(upload_dir, unique_name)
        temp_files.append(file_path)
        
        try:
            file_bytes = await file.read()
            with open(file_path, "wb") as f:
                f.write(file_bytes)
            
            raw_text = extract_text(file_path)
            combined_text += f"\\n--- Document: {file.filename} ---\\n" + raw_text[:5000]
        except Exception as e:
            print(f"[CHECK DOCS ERROR] {file.filename}: {e}")
            pass
            
    # Cleanup temp files
    for temp_file in temp_files:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
                
    # Call Validator Agent
    try:
        from services.validator import validator
        import asyncio
        result = await validator.validate_documents(combined_text, application_type)
        return result
    except Exception as e:
        print(f"[LLM DOC CHECK ERROR] {e}")
        return {"missing": []}



@router.post("/{case_id}/upload")
async def upload_documents(case_id: int, files: list[UploadFile] = File(...), current_user: dict = Depends(get_current_user)):
    """
    Multi-file upload pipeline per case:
    1. Saves each file to disk
    2. Runs OCR on each file
    3. Stores all text chunks into ChromaDB (same case collection)
    4. Runs ONE consolidated risk analysis across all documents
    5. Saves results to DB and updates case status
    """
    if current_user["role_id"] not in [5, 1]:
        raise HTTPException(status_code=403, detail="Only Agents/Brokers can upload documents.")

    case_record = fetch_one("SELECT applicant_name FROM underwriting_cases WHERE id = %s", (case_id,))
    if not case_record:
        raise HTTPException(status_code=404, detail="Case not found.")
    applicant_name = case_record["applicant_name"]

    allowed_types = [".pdf", ".jpg", ".jpeg", ".png"]
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    processed = []
    errors = []

    # Import services once at the start of request to catch any import errors early
    try:
        from services.ocr_service import extract_text
        from services.vector_store import store_document
        from services.risk_engine import analyse_risk
    except Exception as import_err:
        raise HTTPException(status_code=500, detail=f"AI service import error: {str(import_err)}")

    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_types:
            errors.append({"file": file.filename, "error": f"Unsupported type {ext}"})
            continue

        safe_name = "".join([c if c.isalnum() else "_" for c in applicant_name])
        original_slug = "".join([c if c.isalnum() else "_" for c in os.path.splitext(file.filename)[0]])
        unique_name = f"c{case_id}_{original_slug}_{uuid.uuid4().hex[:4]}{ext}"
        file_path = os.path.join(upload_dir, unique_name)

        try:
            file_bytes = await file.read()
            with open(file_path, "wb") as f:
                f.write(file_bytes)

            # OCR text extraction
            raw_text = extract_text(file_path)
            print(f"[OCR] {file.filename}: {len(raw_text)} chars extracted")

            if applicant_name.lower() not in raw_text.lower():
                print(f"[ERROR] Name mismatch! Applicant '{applicant_name}' not found in document '{file.filename}'. Rejecting upload.")
                raise Exception(f"Name Mismatch: The uploaded document does not belong to the applicant '{applicant_name}'. Please upload a valid document.")

            # Save document record to DB
            doc_id = execute(
                "INSERT INTO documents (case_id, file_name, file_path) VALUES (%s, %s, %s)",
                (case_id, unique_name, file_path)
            )

            # Run GraphRAG Pipeline (ChromaDB + ArangoDB unified indexing)
            from services.graphrag_pipeline import GraphRagPipeline
            pipeline = GraphRagPipeline()
            pipeline_result = await pipeline.process_document_flow(
                case_id=case_id,
                file_path=file_path,
                file_name=unique_name
            )

            # Save OCR record (cap at 5000 chars for DB storage)
            structured = json.dumps({
                "extracted_chars": len(raw_text),
                "file": unique_name,
                "ai_summary": pipeline_result.get("summary", "")
            })
            execute(
                "INSERT INTO ocr_extracted_data (document_id, raw_text, structured_data) VALUES (%s, %s, %s)",
                (doc_id, raw_text[:5000], structured)
            )

            processed.append({"file": unique_name, "chars": len(raw_text), "doc_id": doc_id})

        except Exception as e:
            import traceback
            err_detail = traceback.format_exc()
            print(f"[UPLOAD ERROR] {file.filename}: {err_detail}")
            errors.append({"file": file.filename, "error": str(e)})

    if not processed:
        error_msgs = [e['error'] for e in errors]
        error_str = " ".join(error_msgs)
        # Update case status to Intake Processing - Error
        execute("UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = 'Intake Processing - Error') WHERE id = %s", (case_id,))
        raise HTTPException(
            status_code=400,
            detail=error_str
        )

    # ONE consolidated pipeline via Agent 1 (Orchestrator)
    try:
        from services.orchestrator import orchestrator
        import asyncio
        risk_result = await orchestrator.process_new_application(case_id=case_id, files=files)
        print(f"[Orchestrator] Case {case_id}: score={risk_result.get('risk_score')}, level={risk_result.get('risk_level')}")

        execute("DELETE FROM risk_assessments WHERE case_id = %s", (case_id,))
        execute(
            "INSERT INTO risk_assessments (case_id, risk_score, risk_level, confidence_score, findings) VALUES (%s, %s, %s, %s, %s)",
            (case_id, risk_result["risk_score"], risk_result["risk_level"], risk_result.get("ai_confidence", 0.85), json.dumps(risk_result))
        )
        # All cases require manual underwriter review (No Auto-Approve)
        new_status = "Underwriter Review"
        execute("UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = %s) WHERE id = %s", (new_status, case_id))

        # ── Trigger initial underwriter notification & start SLA clock ──
        try:
            from services.escalation_service import trigger_initial_notification
            trigger_initial_notification(case_id)
        except Exception as mail_err:
            # Non-fatal — log and continue
            print(f"[MAIL WARNING] Initial notification failed for case_id={case_id}: {mail_err}")

    except Exception as e:
        import traceback
        print(f"[RISK ERROR] {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Risk analysis failed: {str(e)}")

    return {
        "message": f"{len(processed)}/{len(files)} file(s) processed successfully.",
        "files_processed": processed,
        "files_skipped": errors,
        "risk_score": risk_result["risk_score"],
        "risk_level": risk_result["risk_level"],
        "recommendation": risk_result["recommendation"]
    }

@router.post("/{case_id}/re-evaluate")
async def re_evaluate_case(case_id: int):
    """Re-runs risk analysis for a case."""
    try:
        from services.risk_engine import analyse_risk
        risk_result = analyse_risk(case_id=case_id)
        
        execute("DELETE FROM risk_assessments WHERE case_id = %s", (case_id,))
        execute(
            "INSERT INTO risk_assessments (case_id, risk_score, risk_level, confidence_score, findings) VALUES (%s, %s, %s, %s, %s)",
            (case_id, risk_result["risk_score"], risk_result["risk_level"], risk_result.get("ai_confidence", 0.85), json.dumps(risk_result))
        )
        return {"message": "Re-evaluation complete", "risk_score": risk_result["risk_score"]}
    except Exception as e:
        import traceback
        print(f"[RE-EVAL ERROR] {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

def calculate_past_cases_comparison(case_id: int) -> dict:
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

@router.get("/{case_id}/risk")
async def get_risk_assessment(case_id: int, current_user: dict = Depends(get_current_user)):
    """Returns the latest AI risk assessment for a given case."""
    sql = """
        SELECT risk_score, risk_level, confidence_score, findings, created_at
        FROM risk_assessments WHERE case_id = %s
        ORDER BY created_at DESC LIMIT 1
    """
    result = fetch_one(sql, (case_id,))
    if not result:
        raise HTTPException(status_code=404, detail="No risk assessment found for this case.")

    docs = fetch_all("SELECT id, file_name, created_at FROM documents WHERE case_id = %s ORDER BY created_at DESC", (case_id,))

    # Parse the JSON findings field
    result["findings"] = json.loads(result["findings"]) if isinstance(result["findings"], str) else result["findings"]
    result["uploaded_documents"] = docs
    
    # Calculate past cases comparison dynamically
    result["past_cases_comparison"] = calculate_past_cases_comparison(case_id)
    
    return result


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/{case_id}/chat")
async def chat_with_case_docs(case_id: int, request: ChatRequest, current_user: dict = Depends(get_current_user)):
    """
    RAG chat endpoint to query document contents for standard/senior underwriters, managers, and admins.
    Role 5 (Broker) is strictly forbidden.
    """
    if current_user["role_id"] == 5:
        raise HTTPException(status_code=403, detail="Brokers are not authorized to use the RAG Chat interface.")

    # 1. Fetch relevant context from ChromaDB
    from services.vector_store import query_risk_context
    context_chunks = query_risk_context(query=request.message, case_id=case_id, n_results=5)
    context_text = "\n\n".join(context_chunks) if context_chunks else "No relevant document context found."

    # 2. Get case metadata
    case_record = fetch_one("SELECT applicant_name, policy_type FROM underwriting_cases WHERE id = %s", (case_id,))
    if not case_record:
        raise HTTPException(status_code=404, detail="Case not found.")
    
    applicant_name = case_record["applicant_name"]
    policy_type = case_record["policy_type"]

    # 3. Construct prompt
    prompt = f"""You are an Expert AI Underwriting Assistant.
You are chatting with a professional underwriter (Role ID: {current_user['role_id']}) regarding the case of applicant "{applicant_name}" (Policy Type: "{policy_type}").

Here is the highly relevant patient document context retrieved from the database (ChromaDB):
---
{context_text}
---

CRITICAL INSTRUCTION: You must include citations for all claims you make using the exact source document filenames provided in the context. Format your citations like this: "The patient has a history of hypertension [Source Document: filename.pdf]."

Chat History:
"""
    # Append recent chat history if present
    for chat in request.history[-5:]:
        role = "Underwriter" if chat.get("role") == "user" else "Assistant"
        prompt += f"{role}: {chat.get('content')}\n"

    prompt += f"Underwriter: {request.message}\nAssistant:"

    # 4. Call Mistral AI
    MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
    MISTRAL_MODEL = os.getenv("MISTRAL_LOCAL_MODEL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_MODEL")

    if not MISTRAL_API_KEY or MISTRAL_API_KEY == "your_mistral_key_here":
        return {"response": "Mistral AI API Key is not configured."}

    try:
        from mistralai.client import MistralClient
        from mistralai.models.chat_completion import ChatMessage
        
        kwargs = {"api_key": MISTRAL_API_KEY, "timeout": 300}
        if os.getenv("MISTRAL_MODE") == "Local":
            kwargs["endpoint"] = os.getenv("MISTRAL_LOCAL_URL")
        client = MistralClient(**kwargs)
        response = client.chat(
            model=MISTRAL_MODEL,
            messages=[ChatMessage(role="user", content=prompt)],
            temperature=0.3
        )
        reply = response.choices[0].message.content
        return {"response": reply}
    except Exception as e:
        import traceback
        print(f"[RAG Chat Error] {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"LLM Chat failed: {str(e)}")


class DecisionRequest(BaseModel):
    decision: str
    remarks: str
    referred_to_user_id: Optional[int] = None
    rejection_reason: Optional[str] = None

@router.post("/{case_id}/decision")
async def make_decision(case_id: int, request: DecisionRequest, current_user: dict = Depends(get_current_user)):
    """Logs the final underwriting decision, updates the case, and writes an audit log."""
    if current_user["role_id"] not in [1, 2, 3, 4]:
        raise HTTPException(status_code=403, detail="Not authorized to make underwriting decisions.")

    status_map = {
        "approve": "Approved", 
        "reject": "Rejected", 
        "escalate": "Referred",
        "in_progress": "Risk Analysis In Progress",
        "request_document": "Pending Additional Documents"
    }
    new_status = status_map.get(request.decision.lower())
    if not new_status:
        raise HTTPException(status_code=400, detail="Invalid decision. Use 'approve', 'reject', 'escalate', 'in_progress', or 'request_document'.")

    try:
        from database.connection import fetch_one, fetch_all
        
        final_decision = request.decision
        final_status = new_status
        final_remarks = request.remarks
        
        # Check if case is escalated and if user is a standard Underwriter
        case_row = fetch_one("SELECT cs.status_name AS status, uc.rejection_count FROM underwriting_cases uc LEFT JOIN case_statuses cs ON uc.status_id = cs.id WHERE uc.id = %s", (case_id,))
        if not case_row:
            raise HTTPException(status_code=404, detail="Case not found.")
            
        if case_row["status"] == "Referred" and current_user["role_id"] == 4:
            raise HTTPException(status_code=403, detail="Standard Underwriters cannot review or take action on escalated cases.")
            
        current_rejections = case_row["rejection_count"] if case_row["rejection_count"] else 0
        
        if request.decision.lower() == "reject":
            current_rejections += 1
            config_row = fetch_one("SELECT config_value FROM system_config WHERE config_key = 'MAX_REJECTIONS'")
            max_rej = int(config_row["config_value"]) if config_row else 3
            
            if current_rejections >= max_rej:
                final_decision = "escalate"
                final_status = "Referred"
                final_remarks = f"Auto-escalated: Case rejected {current_rejections} times. Last remarks: " + request.remarks
                current_rejections = 0 # reset after escalation
                
                from services.mail_service import send_bulk_emails
                try:
                    managers = fetch_all("SELECT id, username as name, email FROM users WHERE role_id = 3 AND is_active = 1")
                    if managers:
                        subject = f"[IUA] 🚨 ESCALATED: Case ID {case_id} — Auto-Escalation"
                        body = f"Case {case_id} was automatically escalated after {max_rej} sequential rejections.<br>Last remarks: {request.remarks}"
                        send_bulk_emails(managers, subject, body)
                except Exception as esc_err:
                    print(f"Auto-escalation email failed: {esc_err}")
            else:
                # Notify broker of rejection
                broker = fetch_one("SELECT u.id, u.username as name, u.email FROM underwriting_cases uc JOIN users u ON uc.user_id = u.id WHERE uc.id = %s", (case_id,))
                if broker and broker["email"]:
                    from services.mail_service import send_bulk_emails
                    try:
                        subject = f"[IUA] ❌ Case {case_id} Rejected"
                        body = f"Your case {case_id} has been rejected.<br>Underwriter Remarks: {request.remarks}<br><br>Please edit the application and upload the correct documents."
                        send_bulk_emails([broker], subject, body)
                    except Exception as e: print(f"Broker rejection email failed: {e}")

        elif request.decision.lower() == "escalate":
            current_rejections = 0 # reset on successful path
            # Send email for manual escalation
            from services.mail_service import send_bulk_emails
            try:
                if request.referred_to_user_id:
                    managers = fetch_all("SELECT id, username as name, email FROM users WHERE id = %s AND is_active = 1", (request.referred_to_user_id,))
                else:
                    managers = fetch_all("SELECT id, username as name, email FROM users WHERE role_id = 3 AND is_active = 1")
                
                if managers:
                    subject = f"[IUA] 🚨 ESCALATED: Case ID {case_id} — Manual Escalation"
                    body = f"Case {case_id} was manually escalated by an Underwriter.<br>Remarks: {request.remarks}"
                    send_bulk_emails(managers, subject, body)
            except Exception as esc_err:
                print(f"Manual escalation email failed: {esc_err}")
                
        elif request.decision.lower() == "request_document":
            # Notify broker to upload missing documents
            broker = fetch_one("SELECT u.id, u.username as name, u.email FROM underwriting_cases uc JOIN users u ON uc.user_id = u.id WHERE uc.id = %s", (case_id,))
            if broker and broker["email"]:
                from services.mail_service import send_bulk_emails
                try:
                    subject = f"[IUA] 📄 Documents Required: Case {case_id}"
                    body = f"Underwriters have requested additional documents for Case {case_id}.<br>Remarks: {request.remarks}<br><br>Please edit the application and upload the requested documents."
                    send_bulk_emails([broker], subject, body)
                except Exception as e: print(f"Broker document request email failed: {e}")
                
        elif request.decision.lower() == "approve":
            current_rejections = 0 # reset on successful path
            
        assigned_to_val = request.referred_to_user_id
        if request.decision.lower() in ["approve", "reject", "request_document", "in_progress"]:
            assigned_to_val = current_user["user_id"]

        execute("UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = %s), underwriter_remarks = %s, rejection_count = %s, assigned_to = %s, rejection_reason = %s WHERE id = %s", (final_status, final_remarks, current_rejections, assigned_to_val, request.rejection_reason, case_id))
        execute(
            "INSERT INTO underwriting_decisions (case_id, user_id, decision, remarks) VALUES (%s, %s, %s, %s)",
            (case_id, current_user["user_id"], final_decision, final_remarks)
        )
        from services.audit_service import log_action
        log_action(current_user["user_id"], "CASE_DECISION", {
            "case_id": case_id,
            "decision": final_decision,
            "remarks": final_remarks
        })

        # ── Stop any pending escalation clock for this case ──────────
        try:
            from services.escalation_service import mark_action_taken
            stopped = mark_action_taken(case_id)
            if stopped:
                print(f"[Escalation] Stopped {stopped} pending escalation(s) for case_id={case_id}")
        except Exception as esc_err:
            print(f"[MAIL WARNING] Could not mark_action_taken for case_id={case_id}: {esc_err}")

        return {"message": f"Case {request.decision}d successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class AddContextRequest(BaseModel):
    text: str

@router.post("/{case_id}/add_context")
async def add_context(case_id: int, request: AddContextRequest, current_user: dict = Depends(get_current_user)):
    """Allows uploading raw text context directly without a PDF file."""
    if current_user["role_id"] not in [5, 1, 2, 3, 4]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    case_record = fetch_one("SELECT applicant_name FROM underwriting_cases WHERE id = %s", (case_id,))
    if not case_record:
        raise HTTPException(status_code=404, detail="Case not found.")

    try:
        from services.vector_store import store_document
        from services.risk_engine import analyse_risk

        # Create a dummy document record
        safe_name = "".join([c if c.isalnum() else "_" for c in case_record["applicant_name"]])
        unique_name = f"{safe_name}_api_context_{uuid.uuid4().hex[:6]}.txt"
        doc_id = execute(
            "INSERT INTO documents (case_id, file_name, file_path) VALUES (%s, %s, %s)",
            (case_id, unique_name, "API_DIRECT_TEXT")
        )

        # Store in OCR to be picked up by risk_engine
        structured = json.dumps({"extracted_chars": len(request.text), "file": unique_name, "ai_summary": "Direct API submission"})
        execute(
            "INSERT INTO ocr_extracted_data (document_id, raw_text, structured_data) VALUES (%s, %s, %s)",
            (doc_id, request.text[:5000], structured)
        )

        # Also store into ChromaDB directly
        store_document(doc_id=doc_id, case_id=case_id, text=request.text)

        # Re-run risk analysis
        risk_result = analyse_risk(case_id=case_id)
        
        execute("DELETE FROM risk_assessments WHERE case_id = %s", (case_id,))
        execute(
            "INSERT INTO risk_assessments (case_id, risk_score, risk_level, confidence_score, findings) VALUES (%s, %s, %s, %s, %s)",
            (case_id, risk_result["risk_score"], risk_result["risk_level"], risk_result.get("ai_confidence", 0.85), json.dumps(risk_result))
        )
        # Update case status
        execute("UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = 'Underwriter Review') WHERE id = %s", (case_id,))

        return {
            "message": "Context added successfully",
            "doc_id": doc_id,
            "risk_score": risk_result["risk_score"],
            "risk_level": risk_result["risk_level"]
        }
    except Exception as e:
        import traceback
        print(f"[ADD_CONTEXT ERROR] {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))

class EnrichContextRequest(BaseModel):
    api_key: str
    patient_id: str

@router.post("/{case_id}/enrich_context")
async def enrich_context(case_id: int, request: EnrichContextRequest, current_user: dict = Depends(get_current_user)):
    """Simulates Applicant Context Enrichment via external APIs (Hospital/Broker)"""
    if current_user["role_id"] not in [5, 1, 2, 3, 4]:
        raise HTTPException(status_code=403, detail="Not authorized.")

    case_record = fetch_one("SELECT applicant_name FROM underwriting_cases WHERE id = %s", (case_id,))
    if not case_record:
        raise HTTPException(status_code=404, detail="Case not found.")

    try:
        from services.vector_store import store_document
        from services.risk_engine import analyse_risk
        
        # Simulate fetching data from Hospital/Broker APIs
        simulated_medical_history = "Patient has a documented history of mild asthma. Managed well with occasional inhaler use."
        simulated_claims_data = "No past claims detected in the broker network."
        simulated_policy_data = "Requested standard health cover. No prior policy lapses."
        
        enriched_text = f"""[SECURE EXTERNAL API ENRICHMENT]
Patient External ID: {request.patient_id}
Medical History (from Hospital API): {simulated_medical_history}
Claims Data (from Broker API): {simulated_claims_data}
Policy Data (from Broker API): {simulated_policy_data}
"""
        
        # Store enriched context as a dummy document
        safe_name = "".join([c if c.isalnum() else "_" for c in case_record["applicant_name"]])
        unique_name = f"{safe_name}_enrichment_{uuid.uuid4().hex[:6]}.txt"
        doc_id = execute(
            "INSERT INTO documents (case_id, file_name, file_path) VALUES (%s, %s, %s)",
            (case_id, unique_name, "API_EXTERNAL_ENRICHMENT")
        )

        structured = json.dumps({"extracted_chars": len(enriched_text), "file": unique_name, "ai_summary": "Context enrichment via external hospital/broker API"})
        execute(
            "INSERT INTO ocr_extracted_data (document_id, raw_text, structured_data) VALUES (%s, %s, %s)",
            (doc_id, enriched_text, structured)
        )

        store_document(doc_id=doc_id, case_id=case_id, text=enriched_text)

        # Re-run risk analysis
        risk_result = analyse_risk(case_id=case_id)
        
        execute("DELETE FROM risk_assessments WHERE case_id = %s", (case_id,))
        execute(
            "INSERT INTO risk_assessments (case_id, risk_score, risk_level, confidence_score, findings) VALUES (%s, %s, %s, %s, %s)",
            (case_id, risk_result["risk_score"], risk_result["risk_level"], risk_result.get("ai_confidence", 0.85), json.dumps(risk_result))
        )
        execute("UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = 'Underwriter Review') WHERE id = %s", (case_id,))

        return {
            "message": "Applicant context enriched successfully",
            "doc_id": doc_id,
            "risk_score": risk_result["risk_score"],
            "risk_level": risk_result["risk_level"]
        }
    except Exception as e:
        import traceback
        print(f"[ENRICH_CONTEXT ERROR] {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL CASES
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/historical")
async def get_historical_cases(
    search: str = "",
    status: str = "",
    policy_type: str = "",
    date_from: str = "",
    date_to: str = "",
    current_user: dict = Depends(get_current_user)
):
    """Returns completed (Approved / Rejected) cases with optional filters."""
    role_id = current_user["role_id"]
    user_id = current_user["user_id"]

    sql = """
        SELECT
            uc.id, uc.case_number, uc.applicant_name, uc.policy_type,
            uc.application_type,
            pt.product_name AS product_type,
            uc.requested_coverage, cs.status_name AS status,
            uc.priority, uc.sla_due_at, uc.created_at,
            uc.underwriter_remarks, uc.rejection_reason,
            uc.user_id, uc.assigned_to,
            COALESCE(u_broker.full_name, u_broker.username) AS broker_name,
            COALESCE(u_uw.full_name, u_uw.username)     AS assigned_user,
            ra.risk_score, ra.risk_level, ra.confidence_score
        FROM underwriting_cases uc
        LEFT JOIN case_statuses cs   ON uc.status_id        = cs.id
        LEFT JOIN product_types pt   ON uc.product_type_id  = pt.id
        LEFT JOIN users u_broker     ON uc.user_id           = u_broker.id
        LEFT JOIN users u_uw         ON uc.assigned_to       = u_uw.id
        LEFT JOIN risk_assessments ra ON ra.case_id          = uc.id
            AND ra.created_at = (
                SELECT MAX(ra2.created_at)
                FROM risk_assessments ra2
                WHERE ra2.case_id = uc.id
            )
        WHERE cs.status_name IN ('Approved', 'Rejected')
    """
    params = []

    if role_id == 5:          # Broker sees only their own historical cases
        sql += " AND uc.user_id = %s"
        params.append(user_id)

    if search:
        sql += " AND (uc.case_number LIKE %s OR uc.applicant_name LIKE %s OR uc.policy_type LIKE %s)"
        like = f"%{search}%"
        params += [like, like, like]

    if status:
        sql += " AND cs.status_name = %s"
        params.append(status)

    if policy_type:
        sql += " AND uc.policy_type = %s"
        params.append(policy_type)

    if date_from:
        sql += " AND DATE(uc.created_at) >= %s"
        params.append(date_from)

    if date_to:
        sql += " AND DATE(uc.created_at) <= %s"
        params.append(date_to)

    sql += " ORDER BY uc.created_at DESC LIMIT 200"

    try:
        return fetch_all(sql, params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# CASE TIMELINE
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{case_id}/timeline")
async def get_case_timeline(case_id: int, current_user: dict = Depends(get_current_user)):
    """
    Returns an ordered list of events for a case:
    Created → Document Uploaded → Risk Analyzed → Comment/Decision → ...
    """
    events = []

    # 1. Case creation
    row = fetch_one(
        """SELECT uc.created_at, uc.applicant_name, uc.policy_type, uc.application_type,
                  COALESCE(u.full_name, u.username) AS actor
           FROM underwriting_cases uc
           LEFT JOIN users u ON uc.user_id = u.id
           WHERE uc.id = %s""",
        (case_id,)
    )
    if row:
        events.append({
            "event_type": "case_created",
            "title": "Case Submitted",
            "description": f"{row['applicant_name']} — {row['policy_type']} ({row['application_type']})",
            "actor": row["actor"] or "Broker",
            "actor_role": "Broker",
            "timestamp": str(row["created_at"]),
            "icon": "create"
        })

    # 2. Documents uploaded
    docs = fetch_all(
        """SELECT d.file_name, d.created_at,
                  COALESCE(u.full_name, u.username) AS actor
           FROM documents d
           LEFT JOIN underwriting_cases uc ON d.case_id = uc.id
           LEFT JOIN users u ON uc.user_id = u.id
           WHERE d.case_id = %s
           ORDER BY d.created_at ASC""",
        (case_id,)
    )
    if docs:
        import datetime
        grouped_docs = []
        current_group = {
            "files": [docs[0]["file_name"]], 
            "actor": docs[0]["actor"], 
            "timestamp": docs[0]["created_at"]
        }
        
        for doc in docs[1:]:
            t1 = doc["created_at"]
            t2 = current_group["timestamp"]
            
            if isinstance(t1, datetime.datetime) and isinstance(t2, datetime.datetime):
                diff = abs((t1 - t2).total_seconds())
            else:
                diff = 0 if str(t1)[:16] == str(t2)[:16] else 999
                
            if diff < 300 and doc["actor"] == current_group["actor"]:
                current_group["files"].append(doc["file_name"])
            else:
                grouped_docs.append(current_group)
                current_group = {
                    "files": [doc["file_name"]], 
                    "actor": doc["actor"], 
                    "timestamp": doc["created_at"]
                }
        grouped_docs.append(current_group)

        for g in grouped_docs:
            file_count = len(g["files"])
            if file_count <= 2:
                desc = ", ".join(g["files"])
            else:
                desc = f"{file_count} documents uploaded"
                
            events.append({
                "event_type": "document_uploaded",
                "title": "Documents Uploaded" if file_count > 1 else "Document Uploaded",
                "description": desc,
                "actor": g["actor"] or "Broker",
                "actor_role": "Broker",
                "timestamp": str(g["timestamp"]),
                "icon": "upload_file"
            })

    # 3. Risk assessments
    risks = fetch_all(
        "SELECT risk_score, risk_level, created_at FROM risk_assessments WHERE case_id = %s ORDER BY created_at ASC",
        (case_id,)
    )
    for r in risks:
        events.append({
            "event_type": "risk_analyzed",
            "title": "AI Risk Analysis Completed",
            "description": f"Risk Score: {r['risk_score']} / 100 — Level: {r['risk_level']}",
            "actor": "AI Engine",
            "actor_role": "System",
            "timestamp": str(r["created_at"]),
            "icon": "psychology"
        })

    # 4. Decisions
    decisions = fetch_all(
        """SELECT ud.decision, ud.remarks, ud.created_at,
                  COALESCE(u.full_name, u.username) AS actor, u.role_id
           FROM underwriting_decisions ud
           LEFT JOIN users u ON ud.user_id = u.id
           WHERE ud.case_id = %s
           ORDER BY ud.created_at ASC""",
        (case_id,)
    )
    role_labels = {1: "Admin", 2: "Manager", 3: "Senior Underwriter", 4: "Underwriter", 5: "Broker"}
    decision_titles = {
        "approve": "Case Approved ✅",
        "reject": "Case Rejected ❌",
        "escalate": "Case Referred / Escalated ⬆️",
        "request_document": "Additional Documents Requested 📄",
        "in_progress": "Marked In Progress 🔄"
    }
    for d in decisions:
        events.append({
            "event_type": f"decision_{d['decision']}",
            "title": decision_titles.get(d["decision"], f"Decision: {d['decision']}"),
            "description": d["remarks"] or "",
            "actor": d["actor"] or "Underwriter",
            "actor_role": role_labels.get(d["role_id"], "Underwriter"),
            "timestamp": str(d["created_at"]),
            "icon": "gavel"
        })

    # 5. Comments
    comments = fetch_all(
        """SELECT cc.comment_text, cc.created_at,
                  COALESCE(u.full_name, u.username) AS actor, u.role_id
           FROM case_comments cc
           LEFT JOIN users u ON cc.user_id = u.id
           WHERE cc.case_id = %s
           ORDER BY cc.created_at ASC""",
        (case_id,)
    )
    for c in comments:
        events.append({
            "event_type": "comment_added",
            "title": "Comment Added 💬",
            "description": c["comment_text"],
            "actor": c["actor"] or "User",
            "actor_role": role_labels.get(c["role_id"], "User"),
            "timestamp": str(c["created_at"]),
            "icon": "comment"
        })

    # Sort all events by timestamp
    events.sort(key=lambda x: x["timestamp"])
    return events


# ─────────────────────────────────────────────────────────────────────────────
# BIDIRECTIONAL COMMENTS (Broker ↔ Underwriter)
# ─────────────────────────────────────────────────────────────────────────────

class CommentCreate(BaseModel):
    comment_text: str

@router.get("/{case_id}/comments")
async def get_case_comments(case_id: int, current_user: dict = Depends(get_current_user)):
    """Returns all comments for a case, ordered by time."""
    comments = fetch_all(
        """SELECT cc.id, cc.comment_text, cc.created_at,
                  u.id AS user_id,
                  COALESCE(u.full_name, u.username) AS author_name,
                  u.role_id
           FROM case_comments cc
           LEFT JOIN users u ON cc.user_id = u.id
           WHERE cc.case_id = %s
           ORDER BY cc.created_at ASC""",
        (case_id,)
    )
    role_labels = {1: "Admin", 2: "Underwriting Manager", 3: "Senior Underwriter", 4: "Underwriter", 5: "Broker"}
    result = []
    for c in comments:
        result.append({
            "id": c["id"],
            "comment_text": c["comment_text"],
            "created_at": str(c["created_at"]),
            "user_id": c["user_id"],
            "author_name": c["author_name"] or "Unknown",
            "role_id": c["role_id"],
            "role_label": role_labels.get(c["role_id"], "User")
        })
    return result


@router.post("/{case_id}/comments")
async def add_case_comment(case_id: int, body: CommentCreate, current_user: dict = Depends(get_current_user)):
    """Adds a comment to a case. Both brokers and underwriters can post."""
    if not body.comment_text.strip():
        raise HTTPException(status_code=400, detail="Comment cannot be empty.")

    # Verify case exists
    case_row = fetch_one("SELECT id, user_id FROM underwriting_cases WHERE id = %s", (case_id,))
    if not case_row:
        raise HTTPException(status_code=404, detail="Case not found.")

    try:
        execute(
            "INSERT INTO case_comments (case_id, user_id, comment_text) VALUES (%s, %s, %s)",
            (case_id, current_user["user_id"], body.comment_text.strip())
        )

        # Update case status to "On Hold"
        execute(
            "UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = 'On Hold') WHERE id = %s",
            (case_id,)
        )

        from services.mail_service import send_bulk_emails

        # Notify the other party via underwriter_remarks for broker notifications
        if current_user["role_id"] == 5:
            # Broker posted — notify underwriter
            execute(
                "UPDATE underwriting_cases SET underwriter_remarks = %s WHERE id = %s",
                (f"[Broker Comment] {body.comment_text.strip()[:200]}", case_id)
            )
            try:
                assigned = fetch_one("SELECT u.email, u.username as name FROM underwriting_cases uc JOIN users u ON uc.assigned_to = u.id WHERE uc.id = %s", (case_id,))
                if assigned and assigned["email"]:
                    send_bulk_emails([assigned], f"[IUA] 💬 New Comment on Case {case_id}", f"A new comment was added to case {case_id}:<br><br>{body.comment_text}<br><br>Status is now On Hold.")
            except Exception as e:
                print(f"Broker comment email failed: {e}")
        else:
            # Underwriter posted — update remarks so broker sees notification
            execute(
                "UPDATE underwriting_cases SET underwriter_remarks = %s WHERE id = %s",
                (body.comment_text.strip()[:200], case_id)
            )
            try:
                broker = fetch_one("SELECT u.email, u.username as name FROM underwriting_cases uc JOIN users u ON uc.user_id = u.id WHERE uc.id = %s", (case_id,))
                if broker and broker["email"]:
                    send_bulk_emails([broker], f"[IUA] 💬 New Comment on Case {case_id}", f"A new comment was added to your case {case_id}:<br><br>{body.comment_text}<br><br>Status is now On Hold.")
            except Exception as e:
                print(f"UW comment email failed: {e}")

        from services.audit_service import log_action
        log_action(current_user["user_id"], "CASE_COMMENT", {
            "case_id": case_id,
            "comment": body.comment_text[:100]
        })

        return {"message": "Comment added successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
