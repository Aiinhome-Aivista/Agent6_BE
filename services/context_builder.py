class ContextBuilder:
    """
    Context Summary Agent
    Compiles raw OCR data, graph data, and enrichment data into a single payload.
    """
    def __init__(self):
        self.name = "Context Builder"

    def build_context(self, case_id: int, ocr_data: str, graph_data: dict, enrichment_data: dict) -> str:
        print(f"[{self.name}] Building unified context payload for Case {case_id}")
        
        context = f"=== CASE ID: {case_id} ===\n\n"
        
        context += "--- OCR EXTRACTED TEXT ---\n"
        context += f"{ocr_data[:10000]}\n\n" # Limit for token size
        
        context += "--- GRAPH ENTITIES (ArangoDB) ---\n"
        context += f"{str(graph_data)}\n\n"
        
        context += "--- THIRD PARTY ENRICHMENT ---\n"
        context += f"{str(enrichment_data)}\n\n"
        
        return context

context_builder = ContextBuilder()
