class DecisionEngine:
    """
    Agent 6: Decision Agent
    Determines STP rules: Accept, Refer, Decline.
    """
    def __init__(self):
        self.name = "Decision Agent"

    def evaluate_stp(self, risk_score: int, fraud_flags: list, missing_docs: list) -> dict:
        """
        Rules for STP Auto-Approval:
        - Risk Score < 40
        - 0 Fraud Flags
        - 0 Missing Docs
        """
        print(f"[{self.name}] Evaluating STP rules")

        if len(fraud_flags) > 0:
            return {
                "decision": "Refer to Underwriter",
                "stp_approved": False,
                "reasoning": "Fraud flags detected."
            }
        
        if len(missing_docs) > 0:
            return {
                "decision": "Refer to Underwriter",
                "stp_approved": False,
                "reasoning": "Missing mandatory documents."
            }

        if risk_score >= 40:
            return {
                "decision": "Refer to Underwriter",
                "stp_approved": False,
                "reasoning": "Risk Score exceeds STP threshold."
            }
            
        # Hard decline check (simplified for now)
        if risk_score > 90:
             return {
                "decision": "Decline",
                "stp_approved": False,
                "reasoning": "Risk Score critically high."
            }

        return {
            "decision": "Accept",
            "stp_approved": True,
            "reasoning": "Passed all STP checks cleanly."
        }

decision_engine = DecisionEngine()
