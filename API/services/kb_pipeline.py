"""
Knowledge Base Pipeline Service
Handles: OCR → LLM (Relevance Check + Graph Extraction) → ArangoDB + ChromaDB
Used by: Knowledge Base upload endpoint + scheduled re-indexing job
"""
import os
import json
import re
from datetime import datetime
from arango import ArangoClient
from services.ocr_service import extract_text
import chromadb
from chromadb.utils import embedding_functions

# ─── Config ───────────────────────────────────────────────────────────────────
ARANGO_HOST     = os.getenv("ARANGO_HOST", "https://a71fd1666bd9.arangodb.cloud:8529")
ARANGO_DB       = os.getenv("ARANGO_DB", "underwriting_db")
ARANGO_USERNAME = os.getenv("ARANGO_USERNAME", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "TnHBO0Y4FwKptmr6GxrL")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL   = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

RELEVANCE_THRESHOLD = 75   # Documents below this score are rejected

# ─── ChromaDB — Knowledge Base collection ─────────────────────────────────────
CHROMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_store")
_chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
_ef = embedding_functions.DefaultEmbeddingFunction()

kb_collection = _chroma_client.get_or_create_collection(
    name="knowledge_base",
    embedding_function=_ef,
    metadata={"hnsw:space": "cosine"}
)


# ─── Final Healthcare KG Extraction Prompt ────────────────────────────────────
def build_kb_prompt(raw_summary: str) -> str:
    return f"""
You are an Enterprise Healthcare & Insurance Knowledge Graph Intelligence Engine.

PRIMARY OBJECTIVE:
Construct an enterprise underwriting intelligence graph focused on:
- coverage rules
- admissibility logic
- exclusions
- waiting periods
- reimbursement conditions
- diagnostic eligibility
- underwriting risks
- hospitalization requirements
- claim payout logic
- disease-policy dependencies

SECONDARY OBJECTIVE:
Extract generic medical and insurance entities.

Focus on reasoning-centric graph generation rather than generic entity extraction.
Prefer semantic insurance intelligence relationships over generic co-occurrence relationships.

Analyze the following document and construct a comprehensive semantic knowledge graph.

Identify:
1. Entities and their attributes
2. Explicit and implicit semantic relationships
3. Temporal events and timelines
4. Risk indicators and fraud signals
5. Policy rules, coverage benefits, exclusions, waiting periods
6. Patient journey and disease progression (if clinical/patient document)

━━━━━━━━━━━━━━━━━━━━━━━━
DOMAIN RELEVANCE CHECK (PRIORITY FIRST)
━━━━━━━━━━━━━━━━━━━━━━━━

Before extracting anything, evaluate whether this document is relevant
to the following domain:

  Healthcare · Medical · Clinical · Insurance · Underwriting ·
  Pharmacy · Diagnostics · Hospital · Patient Records · Claims ·
  Lab Reports · Prescriptions · Discharge Summaries · EHR/EMR ·
  Health Policies · Treatment Plans · Risk Assessment

Score the document's domain relevance from 0 to 100:

  90-100 -> Highly Relevant  (medical report, claim form, prescription, lab result, underwriting manual)
  70-89  -> Relevant         (health-related document with some non-medical content)
  36-69  -> Partially Relevant (mentions health/insurance but primary topic differs)
  0-35   -> Not Relevant     (completely unrelated: invoice, legal contract, news, etc.)

Rules:
- If relevance_score < {RELEVANCE_THRESHOLD} -> set graph_extraction_blocked: true
  and return ONLY the relevance block. Do NOT extract nodes, edges, or events.
- If relevance_score >= {RELEVANCE_THRESHOLD} -> set graph_extraction_blocked: false
  and proceed with full extraction below.
- Be strict. A general financial report is NOT relevant even if it mentions insurance.
- A cooking recipe or travel document scores 0.

━━━━━━━━━━━━━━━━━━━━━━━━
DOCUMENT CLASSIFICATION RULE
━━━━━━━━━━━━━━━━━━━━━━━━

1. Determine if this document is a CLINICAL/PATIENT RECORD (discharge summary, lab report, claim file, doctor note) OR an INSURANCE UNDERWRITING MANUAL/RULEBOOK/POLICY GUIDE (e.g. Care Supreme policy manual, guidelines).
2. If it is an Underwriting Manual or Policy Guide:
   - DO NOT hallucinate or invent mock patients, doctors, medical reports, prescriptions, claims, or appointments.
   - Do NOT use Patient (P-), Doctor (D-), Hospital (H-), Medical_Report (R-), Prescription (RX-), or Lab_Test (LT-) nodes unless they are explicitly named templates.
   - Instead, extract INSURANCE POLICY/PRODUCT (INS-), UNDERWRITING RULE/CLAUSE (URW-), RISK FACTOR (RF-), CHRONIC CONDITION (CHR-), and DISEASE (DIS-).
   - Transform policy clauses into semantic underwriting rules.
   - Generate UNDERWRITING_RULE nodes for:
       * waiting periods
       * exclusions
       * admissibility criteria
       * payout conditions
       * reimbursement logic
       * room rent limits
       * ICU caps
       * hospitalization requirements
       * PED restrictions
       * disease eligibility rules

   - Infer underwriting-semantic relationships:
       * Disease eligibility chains
       * Claim admissibility logic
       * Diagnostic dependency graphs
       * Risk escalation paths
       * Coverage dependency structures

   - Convert tabular eligibility criteria into graph relationships.

   - Focus more on underwriting reasoning than generic entity extraction.
━━━━━━━━━━━━━━━━━━━━━━━━
ENTITY TYPES TO EXTRACT
━━━━━━━━━━━━━━━━━━━━━━━━

Use these exact labels and ID prefixes:

P-    -> Patient          (name, age, gender, blood_group, bmi, smoking_status, chronic_conditions, allergies)
D-    -> Doctor           (name, specialization, qualification, license_number, hospital_affiliation)
H-    -> Hospital         (hospital_name, location, hospital_type, accreditation, department)
R-    -> Medical_Report   (visit_date, diagnosis, symptoms, treatment_plan, follow_up_date, report_status)
DIS-  -> Disease          (disease_name, severity, icd_code, snomed_code, progression_stage)
SYM-  -> Symptom          (symptom_name, duration, severity)
MED-  -> Medication       (medication_name, dosage, frequency, duration, rxnorm_code, side_effects)
RX-   -> Prescription     (prescribed_date, prescribing_doctor, duration)
LT-   -> Lab_Test         (test_name, result, normal_range, unit, is_abnormal, loinc_code)
TR-   -> Treatment        (treatment_type, procedure_name, treatment_cost, start_date, end_date, outcome)
INS-  -> Insurance_Policy (provider, policy_number, plan_type, coverage_amount, premium, deductible, co_pay, validity_start, validity_end, status)
CLM-  -> Insurance_Claim  (claim_amount, approved_amount, claim_date, claim_status, rejection_reason)
APT-  -> Appointment      (appointment_date, consultation_type, consultation_fee, status)
MET-  -> Diagnostic_Metric (metric_name, value, unit, normal_range, is_abnormal)
RF-   -> Risk_Factor      (factor_name, severity, category)
ALG-  -> Allergy          (allergen, reaction_type, severity)
CHR-  -> Chronic_Condition (condition_name, icd_code, onset_date, severity)
PRO-  -> Procedure        (procedure_name, procedure_code, cost, date)
URW-  -> Underwriting_Rule (rule_name, threshold, action, exclusion_details, waiting_period_months, copay_percentage, room_rent_limit)

━━━━━━━━━━━━━━━━━━━━━━━━
RELATIONSHIP TYPES
━━━━━━━━━━━━━━━━━━━━━━━━

- HAS_DISEASE
- HAS_SYMPTOM
- HAS_ALLERGY
- HAS_CHRONIC_CONDITION
- TOOK_MEDICATION
- PRESCRIBED
- CONSULTED
- VISITED
- GENERATED_REPORT
- UNDERWENT_TREATMENT
- FILED_CLAIM
- COVERED_BY
- CLAIM_BASED_ON
- WORKS_AT
- DIAGNOSED_WITH
- RECOMMENDED_TREATMENT
- CONFIRMED_BY_TEST
- FOLLOWUP_REQUIRED
- COVERS
- EXCLUDES
- HAS_WAITING_PERIOD
- ELIGIBLE_IF
- ADMISSIBLE_IF
- DENIED_IF
- REQUIRES_TEST
- CLAIM_TRIGGER
- HAS_SUBLIMIT
- HAS_COPAY
- HAS_DEDUCTIBLE
- HAS_PAYOUT_TYPE
- REQUIRES_HOSPITALIZATION
- PRE_EXISTING_CONDITION
- UNDERWRITING_RISK
- HIGH_RISK_PATTERN
- POSSIBLE_FRAUD
- RELATED_TO
- PERFORMED_AT
- INCLUDES
- APPLIES_TO

━━━━━━━━━━━━━━━━━━━━━━━━
EXTRACTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━

1. Assign unique IDs using the prefix convention above (P-001, URW-001, etc.)
2. If a field is NOT found in the document -> set value to null. NEVER guess or hallucinate.
3. Map disease names to ICD-10 codes where possible.
4. Map lab tests to LOINC codes where possible.
5. Map medications to RxNorm codes where possible.
6. Set is_abnormal: true for any lab result outside normal range.
7. Attach timestamps to all relationships where date is available.
8. Infer hidden relationships if medically, policy-wise, or semantically logical.
9. Assign confidence scores (0.0 to 1.0) to ALL relationships.
10. For policy manual documents, ensure UNDERWRITING_RULE nodes map precisely to the policy or product via INCLUDES, and map rules to specific DISEASES via APPLIES_TO or EXCLUDES (e.g. Pre-existing Diabetes waiting period rule applies to Diabetes disease).
11. Detect fraud signals: rapid claims, inflated amounts, name mismatches, duplicate diagnoses.
12. Do not generate disconnected entities.
Every extracted entity must participate in at least one meaningful semantic relationship.

13. For insurance manuals and underwriting guides:
Convert textual rules into reasoning-centric graph structures instead of flat entity links.

14. Prefer semantic underwriting intelligence relationships over generic medical relationships.

15. Diagnostic admissibility tables must be transformed into graph dependency chains.

Example:
Dengue -> REQUIRES_TEST -> NS1AG
VectorBornePolicy -> ADMISSIBLE_IF -> NS1AG Positive

16. Waiting periods, exclusions, reimbursement conditions, and claim eligibility conditions MUST become UNDERWRITING_RULE nodes.
The generated graph must support:
- GraphRAG retrieval
- underwriting reasoning
- claim admissibility traversal
- semantic policy interpretation
- insurance intelligence analytics
- risk propagation analysis
- disease-policy dependency analysis

17. For insurance policy documents, prioritize extraction of:
- underwriting clauses
- claim eligibility conditions
- reimbursement rules
- exclusions
- waiting periods
- diagnostic admissibility conditions
- disease coverage conditions
- hospitalization triggers

18. Do not create generic RELATED_TO edges if a more meaningful underwriting-semantic relationship can be inferred.

The graph should behave like an underwriting reasoning engine,
not a generic entity graph.

Prefer:
- semantic dependency chains
- underwriting logic traversal
- policy reasoning paths
- admissibility relationships
over flat entity extraction.
━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON. No markdown. No explanation. No wrapper text.

CASE A - If relevance_score < {RELEVANCE_THRESHOLD} (blocked):
{{
  "relevance": {{
    "score": 30,
    "label": "Not Relevant",
    "reason": "This document appears to be a general financial invoice with no healthcare or insurance content.",
    "category": "Financial Invoice",
    "graph_extraction_blocked": true,
    "threshold": {RELEVANCE_THRESHOLD}
  }},
  "nodes": [],
  "edges": [],
  "events": [],
  "fraud_indicators": [],
  "risk_analysis": null,
  "medical_codes": {{}},
  "extraction_confidence": 0.0
}}

CASE B - If relevance_score >= {RELEVANCE_THRESHOLD} (full extraction):
{{
  "relevance": {{
    "score": 94,
    "label": "Highly Relevant",
    "reason": "Document is a medical discharge summary with diagnosis, prescription, and lab results.",
    "category": "Clinical Discharge Summary",
    "graph_extraction_blocked": false,
    "threshold": {RELEVANCE_THRESHOLD}
  }},
  "nodes": [
    {{
      "id": "P-001",
      "label": "Patient",
      "properties": {{
        "name": "John Doe",
        "age": 45,
        "gender": "Male",
        "blood_group": "O+",
        "bmi": 31.2,
        "smoking_status": "Smoker",
        "chronic_conditions": ["Type 2 Diabetes", "Hypertension"],
        "allergies": ["Penicillin"]
      }},
      "confidence": 0.98
    }}
  ],
  "edges": [
    {{
      "from_id": "P-001",
      "to_id": "DIS-001",
      "type": "HAS_DISEASE",
      "confidence": 0.97,
      "timestamp": "2025-01-10",
      "source": "document"
    }}
  ],
  "events": [
    {{
      "event_type": "Hospitalization",
      "date": "2025-01-08",
      "duration_days": 3,
      "entity_id": "P-001",
      "details": "Emergency cardiac admission"
    }}
  ],
  "fraud_indicators": [
    {{
      "type": "RAPID_CLAIM",
      "description": "Claim filed 3 days after policy activation",
      "severity": "HIGH",
      "confidence": 0.88
    }}
  ],
  "risk_analysis": {{
    "risk_score": 82,
    "risk_level": "HIGH",
    "risk_factors": ["Diabetes", "Hypertension"],
    "fraud_score": 0.72,
    "underwriting_recommendation": "Reject or Escalate",
    "underwriting_flags": [],
    "claim_admissibility": "",
    "coverage_eligibility": "",
    "manual_review_required": false,
    "policy_violation_probability": 0.0
  }},
  "medical_codes": {{
    "icd10": {{"Type 2 Diabetes Mellitus": "E11"}},
    "loinc": {{"HbA1c": "4548-4"}},
    "rxnorm": {{"Metformin": "6809"}}
  }},
  "extraction_confidence": 0.95
}}

━━━━━━━━━━━━━━━━━━━━━━━━
DOCUMENT CONTENT
━━━━━━━━━━━━━━━━━━━━━━━━

{raw_summary}
"""


class KnowledgeBasePipeline:
    def __init__(self):
        self.db = self._init_arango()

    def _init_arango(self):
        try:
            sys_db = ArangoClient(hosts=ARANGO_HOST).db(
                "_system", username=ARANGO_USERNAME, password=ARANGO_PASSWORD
            )
            if not sys_db.has_database(ARANGO_DB):
                sys_db.create_database(ARANGO_DB)
            db = ArangoClient(hosts=ARANGO_HOST).db(
                ARANGO_DB, username=ARANGO_USERNAME, password=ARANGO_PASSWORD
            )
            for coll, edge in [("kb_entities", False), ("kb_relationships", True)]:
                if not db.has_collection(coll):
                    db.create_collection(coll, edge=edge)
            if not db.has_graph("knowledge_base_graph"):
                db.create_graph("knowledge_base_graph")
            graph = db.graph("knowledge_base_graph")
            if not graph.has_edge_definition("kb_relationships"):
                graph.create_edge_definition(
                    edge_collection="kb_relationships",
                    from_vertex_collections=["kb_entities"],
                    to_vertex_collections=["kb_entities"]
                )
            print("[KB ArangoDB] Connected and initialized kb_entities + kb_relationships.")
            return db
        except Exception as e:
            print(f"[KB ArangoDB Init Error] {e}")
            return None

    async def _call_llm(self, prompt: str) -> str:
        if not MISTRAL_API_KEY or MISTRAL_API_KEY in ("", "your_mistral_key_here"):
            return "{}"
        try:
            from mistralai.client import MistralClient
            from mistralai.models.chat_completion import ChatMessage
            client = MistralClient(api_key=MISTRAL_API_KEY, timeout=300)
            response = client.chat(
                model=MISTRAL_MODEL,
                messages=[ChatMessage(role="user", content=prompt)],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[KB LLM Error] {e}")
            return "{}"

    async def _quick_relevance_check(self, raw_text: str, file_name: str) -> dict:
        prompt = f"""You are a Domain Relevance Validator for a Healthcare Knowledge Graph.

Determine if this document is relevant to the following domains:
Healthcare, Medical, Clinical, Health Insurance, Underwriting, Pharmacy, Diagnostics, Treatment, Patient Records, Underwriting Guidelines.

Strictly evaluate the first 3000 characters of the document:
---
FILE NAME: {file_name}
CONTENT EXCERPT:
{raw_text[:3000]}
---

Return a valid JSON object. For the relevance score, do NOT just default to 95 or 100. Give a highly precise and realistic score between 0 and 100 based on how dense and specific the medical/insurance terminology is. An average brochure might be 82-88, while a highly technical underwriting manual might be 96-99.
{{
  "score": <0-100 relevance score>,
  "label": <"Highly Relevant" | "Relevant" | "Partially Relevant" | "Not Relevant">,
  "category": <automatically identified specific category, e.g. "Health Insurance Manual", "Discharge Summary">,
  "reason": <short 1-2 sentence explanation of the relevance score and domain mapping>,
  "graph_extraction_blocked": <true if score < {RELEVANCE_THRESHOLD} else false>,
  "company_name": <detected insurance provider name, or null if not found>,
  "product_name": <detected specific policy/product name, or null if not found>,
  "insurance_category": <"Health" | "Life" | "Auto" | "Property" | "Unknown">,
  "document_type": <"Brochure" | "Policy Wording" | "Premium Chart" | "Manual" | "Prospectus" | "Unknown">
}}

Return ONLY the JSON. No markdown. No comments.
"""
        raw_resp = await self._call_llm(prompt)
        res = self._parse_json(raw_resp)
        if "score" not in res:
            res = {
                "score": 0,
                "label": "Not Relevant",
                "category": "Unknown",
                "reason": "Failed to parse relevance validation response.",
                "graph_extraction_blocked": True,
                "company_name": None,
                "product_name": None,
                "insurance_category": "Unknown",
                "document_type": "Unknown"
            }
        return res

    async def _generate_raw_summary(self, raw_text: str, file_name: str) -> str:
        """
        Stage 1 — Generate a comprehensive raw summary from OCR text.
        This summary is then fed to Stage 2 (KG extraction prompt) for
        structured knowledge graph output.
        """
        prompt = f"""You are an Expert Healthcare & Insurance Document Analyst.

Review this document and provide a comprehensive, detailed raw summary covering
all of the following sections that are present:

- Patient demographics and bio-data (name, age, gender, blood group, BMI, etc.)
- Medical history, symptoms, chronic conditions, and allergies
- Diagnostic results, lab measurements, and their reference ranges
- Medications prescribed (name, dosage, frequency, duration)
- Treatments, procedures, and surgical interventions
- Insurance policy details (provider, plan, coverage, premium, deductible)
- Claims history, billing, and payment information
- Risk factors and underwriting concerns
- Doctor/hospital details and visit dates
- Follow-up plans and recommendations

Be thorough and preserve ALL medical codes (ICD-10, LOINC, RxNorm),
numeric values, dates, and quantitative data exactly as they appear.
Do not omit any clinically or financially relevant detail.

DOCUMENT CONTENT:
{raw_text[:15000]}
"""
        summary = await self._call_llm(prompt)
        if not summary or summary == "{}":
            summary = (
                f"Automatic summary of {file_name}. "
                f"Document content length: {len(raw_text)} characters. "
                f"Raw text excerpt: {raw_text[:3000]}"
            )
        return summary

    def _parse_json(self, raw: str) -> dict:
        try:
            cleaned = re.sub(r'^```json\s*|\s*```$', '', raw.strip(), flags=re.MULTILINE)
            return json.loads(cleaned)
        except Exception as e:
            print(f"[KB JSON Parse Error] {e}")
            return {}

    async def process(self, kb_id: int, file_path: str, file_name: str) -> dict:
        """
        Full three-stage pipeline with early exit relevance validation (Stage 0):
          1. OCR → Extract raw text
          2. Stage 0 LLM → Quick relevance check. If blocked → stop and exit immediately.
          3. Stage 1 LLM → Generate comprehensive raw summary (if passed)
          4. Stage 2 LLM → KG extraction from summary (if passed)
          5. Store to ArangoDB + ChromaDB
        Returns dict with relevance info, raw summary, and processing stats.
        """
        # Step 1: OCR
        raw_text = extract_text(file_path)
        if not raw_text:
            raw_text = f"Knowledge Base document: {file_name}"

        # Step 2: Stage 0 — Quick Relevance Check (Early Exit Gate)
        print(f"[KB Pipeline] Stage 0: Running quick relevance validation for {file_name}...")
        relevance = await self._quick_relevance_check(raw_text, file_name)
        relevance_score = relevance.get("score", 0)
        is_blocked = relevance.get("graph_extraction_blocked", True)

        if is_blocked:
            print(f"[KB Pipeline] Early Exit: BLOCKED at Stage 0 — score={relevance_score} < {RELEVANCE_THRESHOLD} for {file_name}")
            return {
                "relevance": relevance,
                "blocked": True,
                "raw_summary": f"Blocked due to low domain relevance. Category: {relevance.get('category', 'Unknown')}. Reason: {relevance.get('reason')}",
                "extraction_confidence": 0.0,
                "nodes_stored": 0,
                "edges_stored": 0,
                "chunks_indexed": 0
            }

        print(f"[KB Pipeline] Quick validation PASSED (Score: {relevance_score}, Category: {relevance.get('category')}). Running full extraction...")

        # Step 3: Stage 1 — Generate raw summary from OCR text
        print(f"[KB Pipeline] Stage 1: Generating raw summary for kb_id={kb_id} ({file_name})...")
        raw_summary = await self._generate_raw_summary(raw_text, file_name)
        print(f"[KB Pipeline] Stage 1 complete — summary length: {len(raw_summary)} chars")

        # Step 4: Stage 2 — KG extraction from summary
        print(f"[KB Pipeline] Stage 2: Extracting knowledge graph from summary...")
        prompt = build_kb_prompt(raw_summary)
        llm_raw = await self._call_llm(prompt)
        result = self._parse_json(llm_raw)

        # Merge Stage 0 category if not present in Stage 2 response
        if "relevance" in result:
            if "category" not in result["relevance"]:
                result["relevance"]["category"] = relevance.get("category")
        else:
            result["relevance"] = relevance

        extraction_confidence = result.get("extraction_confidence", 0.0)

        # Step 4: Store nodes to ArangoDB
        nodes = result.get("nodes", [])
        edges = result.get("edges", [])
        nodes_stored = 0
        edges_stored = 0

        if self.db:
            kb_ent = self.db.collection("kb_entities")
            kb_rel = self.db.collection("kb_relationships")

            for node in nodes:
                node_key = f"kb_{kb_id}_{node['id'].replace(' ', '_').replace('-', '_')}"
                doc = {
                    "_key": node_key,
                    "kb_id": kb_id,
                    "label": node.get("label", "Unknown"),
                    "name": node.get("properties", {}).get("name", node.get("id")),
                    "properties": node.get("properties", {}),
                    "confidence": node.get("confidence", 1.0),
                    "source_file": file_name,
                    "created_at": datetime.utcnow().isoformat()
                }
                try:
                    kb_ent.insert(doc, overwrite=True)
                    nodes_stored += 1
                except Exception as e:
                    print(f"[KB ArangoDB Node Error] {e}")

            for edge in edges:
                from_id = edge.get('from_id', 'unknown_from')
                to_id = edge.get('to_id', 'unknown_to')
                edge_type = edge.get('type', 'RELATED_TO')
                
                from_key = f"kb_{kb_id}_{from_id.replace(' ', '_').replace('-', '_')}"
                to_key   = f"kb_{kb_id}_{to_id.replace(' ', '_').replace('-', '_')}"
                edge_key = f"kbedge_{kb_id}_{from_id}_{edge_type}_{to_id}"
                edge_key = re.sub(r'[^a-zA-Z0-9_]', '_', edge_key)[:240]
                edoc = {
                    "_key": edge_key,
                    "_from": f"kb_entities/{from_key}",
                    "_to": f"kb_entities/{to_key}",
                    "type": edge_type,
                    "confidence": edge.get("confidence", 1.0),
                    "timestamp": edge.get("timestamp"),
                    "kb_id": kb_id,
                    "source_file": file_name,
                    "created_at": datetime.utcnow().isoformat()
                }
                try:
                    kb_rel.insert(edoc, overwrite=True)
                    edges_stored += 1
                except Exception as e:
                    print(f"[KB ArangoDB Edge Error] {e}")

        # Step 5: Store contextual summary + relationship sentences in ChromaDB
        risk_analysis  = result.get("risk_analysis") or {}
        fraud_items    = result.get("fraud_indicators", [])
        events         = result.get("events", [])

        # Build rich text chunks for vector indexing
        summary_parts = [f"Document: {file_name}"]
        summary_parts.append(f"Relevance: {relevance.get('label')} ({relevance_score}/100)")
        summary_parts.append(f"Relevance Reason: {relevance.get('reason', '')}")
        summary_parts.append(f"Raw Summary: {raw_summary}")

        if risk_analysis:
            summary_parts.append(
                f"Risk Score: {risk_analysis.get('risk_score')} | "
                f"Risk Level: {risk_analysis.get('risk_level')} | "
                f"Recommendation: {risk_analysis.get('underwriting_recommendation')}"
            )
            factors = risk_analysis.get("risk_factors", [])
            if factors:
                summary_parts.append(f"Risk Factors: {', '.join(factors)}")

        for node in nodes:
            props = node.get("properties", {})
            label = node.get("label", "")
            name  = props.get("name") or props.get("disease_name") or props.get("medication_name") or node.get("id")
            summary_parts.append(f"{label}: {name} | {json.dumps(props)}")

        for edge in edges:
            summary_parts.append(
                f"Relationship: {edge.get('from_id')} --[{edge.get('type')}]--> {edge.get('to_id')} "
                f"(confidence: {edge.get('confidence', 1.0)})"
            )

        for fi in fraud_items:
            summary_parts.append(f"FRAUD SIGNAL [{fi.get('severity')}]: {fi.get('type')} — {fi.get('description')}")

        for ev in events:
            summary_parts.append(f"EVENT [{ev.get('event_type')}] on {ev.get('date')}: {ev.get('details')}")

        # Chunk and upsert to ChromaDB
        full_text  = "\n".join(summary_parts)
        chunk_size = 800
        overlap    = 100
        chunks     = []
        start = 0
        while start < len(full_text):
            chunks.append(full_text[start:start + chunk_size])
            start += chunk_size - overlap
        if not chunks:
            chunks = [full_text or f"KB document {file_name}"]

        chunk_ids   = [f"kb_{kb_id}_chunk_{i}" for i in range(len(chunks))]
        chunk_metas = [{
            "kb_id": str(kb_id),
            "file_name": file_name,
            "chunk": i,
            "relevance_score": relevance_score,
            "risk_level": str(risk_analysis.get("risk_level", "UNKNOWN")),
            "company_name": str(relevance.get("company_name") or "Unknown"),
            "product_name": str(relevance.get("product_name") or "Unknown"),
            "category": str(relevance.get("insurance_category") or relevance.get("category") or "Unknown"),
            "document_type": str(relevance.get("document_type") or "Unknown")
        } for i in range(len(chunks))]

        try:
            # Dynamically fetch collection to prevent stale memory ID after truncation/clean scripts
            dyn_kb_collection = _chroma_client.get_or_create_collection(
                name="knowledge_base",
                embedding_function=_ef,
                metadata={"hnsw:space": "cosine"}
            )
            dyn_kb_collection.upsert(documents=chunks, metadatas=chunk_metas, ids=chunk_ids)
            print(f"[KB ChromaDB] Stored {len(chunks)} chunks for kb_id={kb_id}")
        except Exception as e:
            print(f"[KB ChromaDB Error] {e}")

        return {
            "relevance": relevance,
            "blocked": False,
            "raw_summary": raw_summary,
            "extraction_confidence": extraction_confidence,
            "nodes_stored": nodes_stored,
            "edges_stored": edges_stored,
            "chunks_indexed": len(chunks),
            "risk_analysis": risk_analysis,
            "fraud_indicators": fraud_items
        }


# Singleton instance
kb_pipeline = KnowledgeBasePipeline()
