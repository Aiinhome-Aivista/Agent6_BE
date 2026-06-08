import os
import json

class EnrichmentService:
    """
    Agent 3: Enrichment Agent
    Gathers third-party intelligence (e.g., Credit Bureau, MIB, Pharmacy).
    """
    def __init__(self):
        self.name = "Enrichment Agent"

    def fetch_third_party_data(self, applicant_name: str, case_id: int) -> dict:
        """
        Simulates fetching data from MIB, Credit Bureaus, etc.
        """
        print(f"[{self.name}] Fetching external data for Case {case_id}")
        
        # Simulated API responses
        simulated_mib_data = {
            "status": "Clear",
            "undisclosed_conditions": [],
            "confidence_score": 0.95
        }
        
        simulated_credit_data = {
            "score": 750,
            "financial_risk_level": "Low"
        }

        # Inject simulated mismatch for testing purposes if certain names are used
        if applicant_name and "rahul" in applicant_name.lower():
            simulated_mib_data["status"] = "Flagged"
            simulated_mib_data["undisclosed_conditions"] = ["Hypertension"]
            simulated_mib_data["confidence_score"] = 0.88

        return {
            "mib_data": simulated_mib_data,
            "credit_data": simulated_credit_data
        }

enrichment_service = EnrichmentService()
