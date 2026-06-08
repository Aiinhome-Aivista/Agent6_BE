class PricingEngine:
    """
    Agent 5: Pricing Agent
    Determines final premium, discounts, and multiple sum-assured options based on Risk Score.
    """
    def __init__(self):
        self.name = "Pricing Agent"

    def calculate_pricing(self, risk_score: int) -> dict:
        """
        Rules:
        - Risk Score < 30: Apply 10% discount.
        - Risk Score 30-70: Standard base premium.
        - Risk Score > 70: Apply 25% loaded premium.
        Generates max 3 plan options with realistic Add-ons.
        """
        print(f"[{self.name}] Calculating premium for risk score {risk_score}")
        
        discount = 0
        loading = 0
        
        if risk_score < 30:
            discount = 0.10
            narrative = "Applied 10% discount due to Low Risk."
        elif risk_score > 70:
            loading = 0.25
            narrative = "Applied 25% loading due to High Risk."
        else:
            narrative = "Standard base premium applied."

        # Define 3 realistic plans (Base premiums in INR)
        plans = [
            {"sum_assured": 500000, "base_inr": 8500, "addons": [{"name": "Hospital Cash", "price": 400}, {"name": "No Room Rent Capping", "price": 800}]},
            {"sum_assured": 1000000, "base_inr": 12500, "addons": [{"name": "OPD Cover", "price": 1200}, {"name": "Maternity Benefit", "price": 2500}]},
            {"sum_assured": 2500000, "base_inr": 19500, "addons": [{"name": "Critical Illness Cover", "price": 3500}, {"name": "Global Coverage", "price": 4500}]}
        ]

        premium_outputs = []
        for plan in plans:
            discount_amt = plan["base_inr"] * discount
            loading_amt = plan["base_inr"] * loading
            final_premium = plan["base_inr"] - discount_amt + loading_amt
            
            premium_outputs.append({
                "sum_assured": plan["sum_assured"],
                "base_premium": plan["base_inr"],
                "risk_loading_percent": int(loading * 100),
                "discount_percent": int(discount * 100),
                "final_premium": int(final_premium),
                "addons": plan["addons"]
            })

        return {
            "premium_output": premium_outputs,
            "pricing_narrative": narrative
        }

pricing_engine = PricingEngine()
