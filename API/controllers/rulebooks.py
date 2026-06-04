"""
Knowledge Base Controller
Replaces the old rulebooks upload endpoint with the full KB pipeline:
  Upload → OCR → LLM (Relevance Check + Graph) → ArangoDB + ChromaDB → MySQL
"""
import os
import uuid
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from datetime import datetime
from utils.auth_deps import get_current_user
from database.connection import execute, fetch_all, fetch_one
from services.ocr_service import extract_text
from services.kb_pipeline import kb_pipeline, RELEVANCE_THRESHOLD

router = APIRouter(prefix="/rulebooks", tags=["Knowledge Base"])


@router.post("/upload")
async def upload_knowledge_base_doc(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a document to the Knowledge Base.
    Runs full LLM pipeline: Relevance Check → Graph Extraction → ArangoDB + ChromaDB.
    Rejects documents with relevance_score < 75.
    """
    if current_user["role_id"] == 5:
        raise HTTPException(status_code=403, detail="Brokers are not allowed to upload Knowledge Base documents.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF documents are supported.")

    upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "rulebooks")
    os.makedirs(upload_dir, exist_ok=True)

    unique_name = f"kb_{uuid.uuid4().hex[:8]}{ext}"
    file_path = os.path.join(upload_dir, unique_name)

    try:
        file_bytes = await file.read()
        size_mb = len(file_bytes) / (1024 * 1024)
        if size_mb > 25.0:
            raise HTTPException(status_code=400, detail="File size exceeds the 25MB limit.")

        with open(file_path, "wb") as f:
            f.write(file_bytes)

        # Save initial DB record (graph_processed = 0 = pending)
        kb_id = execute(
            """INSERT INTO rule_books 
               (file_name, file_path, uploaded_by, graph_processed, created_at) 
               VALUES (%s, %s, %s, 0, %s)""",
            (file.filename, file_path, current_user["id"], datetime.utcnow())
        )

        # Run full KB pipeline (OCR → LLM → Store)
        result = await kb_pipeline.process(kb_id, file_path, file.filename)

        relevance     = result.get("relevance", {})
        rel_score     = relevance.get("score", 0)
        rel_label     = relevance.get("label", "Unknown")
        rel_reason    = relevance.get("reason", "")
        is_blocked    = result.get("blocked", True)
        category      = relevance.get("category", "General")

        if is_blocked:
            # Relevance too low — delete the physical PDF from disk to save space and remove database record completely
            try:
                os.remove(file_path)
            except Exception:
                pass

            try:
                execute("DELETE FROM rule_books WHERE id = %s", (kb_id,))
            except Exception:
                pass

            raise HTTPException(
                status_code=400,
                detail={
                    "error": "RELEVANCE_TOO_LOW",
                    "relevance_score": rel_score,
                    "threshold": RELEVANCE_THRESHOLD,
                    "category": category,
                    "reason": rel_reason,
                    "message": f"Document rejected due to low domain relevance score ({rel_score}%). Category: {category}."
                }
            )

        # Update DB with processing results
        risk_analysis = result.get("risk_analysis") or {}
        fraud_items   = result.get("fraud_indicators", [])
        fraud_score   = risk_analysis.get("fraud_score")
        risk_level    = risk_analysis.get("risk_level")

        company_name  = relevance.get("company_name")
        product_name  = relevance.get("product_name")
        document_type = relevance.get("document_type")

        execute(
            """UPDATE rule_books SET
               relevance_score       = %s,
               relevance_label       = %s,
               relevance_reason      = %s,
               graph_processed       = 1,
               nodes_count           = %s,
               edges_count           = %s,
               chunks_count          = %s,
               risk_level            = %s,
               fraud_score           = %s,
               raw_summary           = %s,
               extraction_confidence = %s,
               processed_at          = %s,
               category              = %s,
               company_name          = %s,
               product_name          = %s,
               document_type         = %s
               WHERE id = %s""",
            (
                rel_score, rel_label, rel_reason,
                result.get("nodes_stored", 0),
                result.get("edges_stored", 0),
                result.get("chunks_indexed", 0),
                risk_level,
                fraud_score,
                result.get("raw_summary"),
                result.get("extraction_confidence"),
                datetime.utcnow(),
                category,
                company_name,
                product_name,
                document_type,
                kb_id
            )
        )

        return {
            "message": "Document processed and indexed into Knowledge Base successfully.",
            "kb_id": kb_id,
            "file_name": file.filename,
            "relevance_score": rel_score,
            "relevance_label": rel_label,
            "nodes_stored": result.get("nodes_stored", 0),
            "edges_stored": result.get("edges_stored", 0),
            "chunks_indexed": result.get("chunks_indexed", 0),
            "risk_level": risk_level,
            "fraud_score": fraud_score,
            "extraction_confidence": result.get("extraction_confidence"),
            "raw_summary_length": len(result.get("raw_summary", ""))
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        import traceback
        print(f"[KB UPLOAD ERROR] {file.filename}: {traceback.format_exc()}")
        # Mark as error in DB
        try:
            execute(
                "UPDATE rule_books SET graph_processed = 2, processing_error = %s WHERE id = %s",
                (str(e)[:500], kb_id)
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to process document: {str(e)}")


@router.get("/")
async def list_knowledge_base(current_user: dict = Depends(get_current_user)):
    """
    List all Knowledge Base documents with processing stats.
    """
    if current_user["role_id"] == 5:
        raise HTTPException(status_code=403, detail="Brokers are not allowed to view the Knowledge Base.")

    try:
        query = """
            SELECT rb.id, rb.file_name, rb.file_path, rb.created_at,
                   rb.relevance_score, rb.relevance_label, rb.relevance_reason,
                   rb.graph_processed,
                   rb.nodes_count, rb.edges_count, rb.chunks_count,
                   rb.risk_level, rb.fraud_score, rb.processed_at,
                   rb.raw_summary, rb.extraction_confidence,
                   rb.category, rb.company_name, rb.product_name, rb.document_type,
                   u.username AS uploaded_by
            FROM rule_books rb
            JOIN users u ON rb.uploaded_by = u.id
            WHERE rb.graph_processed = 1
            ORDER BY rb.created_at DESC
        """
        rows = fetch_all(query)
        result = []
        for rb in rows:
            size_kb = 0
            if rb["file_path"] and os.path.exists(rb["file_path"]):
                size_kb = round(os.path.getsize(rb["file_path"]) / 1024, 1)

            result.append({
                "id":              rb["id"],
                "file_name":       rb["file_name"],
                "uploaded_by":     rb["uploaded_by"],
                "created_at":      rb["created_at"].isoformat() if hasattr(rb["created_at"], "isoformat") else str(rb["created_at"]),
                "size_kb":         size_kb,
                "relevance_score": rb["relevance_score"],
                "relevance_label": rb["relevance_label"],
                "relevance_reason": rb["relevance_reason"],
                "graph_processed": rb["graph_processed"],   # 0=pending, 1=done, 2=blocked
                "nodes_count":     rb["nodes_count"] or 0,
                "edges_count":     rb["edges_count"] or 0,
                "chunks_count":    rb["chunks_count"] or 0,
                "risk_level":      rb["risk_level"],
                "fraud_score":     rb["fraud_score"],
                "processed_at":    rb["processed_at"].isoformat() if rb["processed_at"] and hasattr(rb["processed_at"], "isoformat") else None,
                "raw_summary":     rb["raw_summary"],
                "extraction_confidence": rb["extraction_confidence"],
                "category":        rb["category"] or "General",
                "company_name":    rb["company_name"],
                "product_name":    rb["product_name"],
                "document_type":   rb["document_type"]
            })
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Knowledge Base: {str(e)}")


@router.get("/{kb_id}")
async def get_knowledge_base_detail(
    kb_id: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Get full details of a single Knowledge Base document including raw summary.
    """
    if current_user["role_id"] == 5:
        raise HTTPException(status_code=403, detail="Brokers are not allowed to view the Knowledge Base.")

    try:
        row = fetch_one(
            """SELECT rb.*, u.username AS uploaded_by
               FROM rule_books rb
               JOIN users u ON rb.uploaded_by = u.id
               WHERE rb.id = %s""",
            (kb_id,)
        )
        if not row:
            raise HTTPException(status_code=404, detail="Knowledge Base document not found.")

        size_kb = 0
        if row["file_path"] and os.path.exists(row["file_path"]):
            size_kb = round(os.path.getsize(row["file_path"]) / 1024, 1)

        # Retrieve ArangoDB Graph Entities and Relationships
        entities = []
        relationships = []
        if kb_pipeline.db:
            try:
                # Query entities
                cursor = kb_pipeline.db.aql.execute(
                    "FOR e IN kb_entities FILTER e.kb_id == @kb_id RETURN e",
                    bind_vars={"kb_id": kb_id}
                )
                entities = [{
                    "id": doc.get("_key"),
                    "label": doc.get("label", "Unknown"),
                    "name": doc.get("name", "Unknown"),
                    "properties": doc.get("properties", {}),
                    "confidence": doc.get("confidence", 1.0)
                } for doc in cursor]

                # Query relationships
                cursor_rel = kb_pipeline.db.aql.execute(
                    "FOR r IN kb_relationships FILTER r.kb_id == @kb_id RETURN r",
                    bind_vars={"kb_id": kb_id}
                )
                relationships = [{
                    "type": doc.get("type"),
                    "from_node": doc.get("_from").split("/")[-1] if doc.get("_from") else "",
                    "to_node": doc.get("_to").split("/")[-1] if doc.get("_to") else "",
                    "confidence": doc.get("confidence", 1.0),
                    "timestamp": doc.get("timestamp")
                } for doc in cursor_rel]
            except Exception as ae:
                print(f"[KB ArangoDB Fetch Error] {ae}")

        return {
            "id":              row["id"],
            "file_name":       row["file_name"],
            "uploaded_by":     row["uploaded_by"],
            "created_at":      row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else str(row["created_at"]),
            "size_kb":         size_kb,
            "relevance_score": row["relevance_score"],
            "relevance_label": row["relevance_label"],
            "relevance_reason": row.get("relevance_reason"),
            "graph_processed": row["graph_processed"],
            "nodes_count":     row["nodes_count"] or 0,
            "edges_count":     row["edges_count"] or 0,
            "chunks_count":    row["chunks_count"] or 0,
            "risk_level":      row["risk_level"],
            "fraud_score":     row["fraud_score"],
            "processed_at":    row["processed_at"].isoformat() if row["processed_at"] and hasattr(row["processed_at"], "isoformat") else None,
            "raw_summary":     row.get("raw_summary"),
            "extraction_confidence": row.get("extraction_confidence"),
            "processing_error": row.get("processing_error"),
            "category":        row.get("category") or "General",
            "tier":            row.get("tier") or "Basic",
            "entities":        entities,
            "relationships":   relationships
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch document details: {str(e)}")
