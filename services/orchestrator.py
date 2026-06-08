import os
import json
from services.ocr_service import extract_text
from services.risk_engine import analyse_risk

# TODO: Refactor these to their new modular services once created
# from services.enrichment_service import enrich_data
# from services.pricing_engine import calculate_pricing
# from services.decision_engine import make_decision
# from services.context_builder import build_context

class AgentOrchestrator:
    """
    Agent 1: The Orchestrator
    Routes tasks sequentially through the multi-agent pipeline.
    """
    def __init__(self):
        self.name = "Orchestrator Agent"

    async def process_new_application(self, case_id: int, files: list) -> dict:
        """
        Main pipeline for processing a new or existing application.
        1. Intake (Agent 2)
        2. Enrichment (Agent 3)
        3. Risk Analysis (Agent 4)
        4. Pricing (Agent 5)
        5. Decision (Agent 6)
        """
        print(f"[Orchestrator] Starting processing for Case {case_id}")
        
        # Step 1 & 2: Currently handled by the unified risk_engine and GraphRAG. 
        # We will wrap the risk_engine call here for now, until all engines are fully split.
        try:
            print(f"[Orchestrator] 👉 Invoking Agent 4: Risk Assessment Engine...")
            from services.risk_engine import analyse_risk
            risk_result = analyse_risk(case_id=case_id)
            
            risk_score = risk_result.get("risk_score", 0)
            fraud_flags = risk_result.get("fraud_flags", [])
            
            print(f"[Orchestrator] 👉 Invoking Agent 3: Enrichment Service...")
            from services.enrichment_service import enrichment_service
            enrichment_data = enrichment_service.fetch_third_party_data("Applicant", case_id)
            if enrichment_data.get("mib_data", {}).get("status") == "Flagged":
                fraud_flags.append("MIB Alert")
            
            print(f"[Orchestrator] 👉 Invoking Agent 5: Pricing Engine...")
            from services.pricing_engine import pricing_engine
            pricing_data = pricing_engine.calculate_pricing(risk_score)
            
            print(f"[Orchestrator] 👉 Invoking Agent 6: Decision Engine...")
            from services.decision_engine import decision_engine
            decision_data = decision_engine.evaluate_stp(risk_score, fraud_flags, missing_docs=[])
            
            # Fetch actual node count from ArangoDB
            node_count = 0
            try:
                from arango import ArangoClient
                arango_client = ArangoClient(hosts=os.getenv("ARANGO_URL"))
                db = arango_client.db(os.getenv("ARANGO_DB"), username=os.getenv("ARANGO_USER"), password=os.getenv("ARANGO_PASSWORD"))
                cursor = db.aql.execute('RETURN LENGTH(FOR e IN entities FILTER e.case_id == @case_id RETURN 1)', bind_vars={'case_id': case_id})
                node_count = [doc for doc in cursor][0]
            except Exception as e:
                print(f"[Orchestrator] Warning: Could not fetch node count from ArangoDB: {e}")

            print(f"[Orchestrator] 👉 Invoking Agent 7: Context Summary Builder...")
            from services.context_builder import context_builder
            contextual_summary = context_builder.build_context(
                case_id=case_id,
                ocr_data=risk_result.get("extracted_details", {}).__str__(), 
                graph_data={"nodes_detected": node_count},
                enrichment_data=enrichment_data
            )
            
            # Stitch the modular results back into the legacy frontend payload format
            risk_result["premium_calculation"] = {
                "premium_output": pricing_data["premium_output"]
            }
            risk_result["decision"] = decision_data["decision"]
            risk_result["stp_approved"] = decision_data["stp_approved"]
            risk_result["pricing_narrative"] = pricing_data["pricing_narrative"]
            risk_result["contextual_summary"] = contextual_summary
            
            print(f"[Orchestrator] Completed processing for Case {case_id}. Decision: {risk_result.get('decision')}")
            return risk_result
            
        except Exception as e:
            print(f"[Orchestrator] Error processing pipeline: {e}")
            raise e

orchestrator = AgentOrchestrator()
