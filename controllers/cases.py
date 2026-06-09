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

        execute("UPDATE underwriting_cases SET status_id = (SELECT id FROM case_statuses WHERE status_name = %s), underwriter_remarks = %s, rejection_count = %s, assigned_to = %s, rejection_reason = %s WHERE id = %s", (final_status, final_remarks, current_rejections, request.referred_to_user_id, request.rejection_reason, case_id))
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
