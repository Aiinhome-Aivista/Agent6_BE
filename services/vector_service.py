from services.vector_store import store_document, query_risk_context, query_rulebook_context, ef, chroma_client

class VectorService:
    """
    Vector Search Service
    Wraps the underlying ChromaDB vector store.
    """
    def __init__(self):
        self.name = "Vector Search Service"
        self.ef = ef
        self.client = chroma_client

    def store(self, doc_id: int, case_id: int, text: str):
        print(f"[{self.name}] Storing vector for doc {doc_id}, case {case_id}")
        return store_document(doc_id, case_id, text)

    def query_context(self, query: str, case_id: int, n_results=3):
        return query_risk_context(query, case_id, n_results)
        
    def query_rulebook(self, query: str, n_results=3):
        return query_rulebook_context(query, n_results)

vector_service = VectorService()
