"""
ChromaDB Vector Store Service
Handles storing and querying document embeddings for RAG-based risk analysis.
Uses ChromaDB's default sentence-transformers embedding for local-first operation.
"""
import chromadb
from chromadb.utils import embedding_functions
import os

# Use a local persistent directory inside the API folder
CHROMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_store")

# Initialize ChromaDB persistent client
chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)

# Use ChromaDB's built-in default embedding function (no API key needed)
ef = embedding_functions.DefaultEmbeddingFunction()

# Get or create the collection for storing underwriting documents
def store_document(doc_id: int, case_id: int, text: str, metadata: dict = {}):
    """
    Chunks and stores document text into ChromaDB with metadata.
    Splits text into ~500-character chunks for better retrieval.
    """
    # Simple character-based chunking
    chunk_size = 500
    chunks = [text[i:i+chunk_size] for i in range(0, len(text), chunk_size)]
    
    if not chunks:
        return
        
    ids = [f"doc_{doc_id}_chunk_{i}" for i in range(len(chunks))]
    metas = [{**metadata, "doc_id": str(doc_id), "case_id": str(case_id), "chunk": i} for i in range(len(chunks))]
    
    dyn_collection = chroma_client.get_or_create_collection(
        name="underwriting_docs",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )
    dyn_collection.upsert(
        documents=chunks,
        metadatas=metas,
        ids=ids
    )
    print(f"[ChromaDB] Stored {len(chunks)} chunks for doc_id={doc_id}, case_id={case_id}")

def query_risk_context(query: str, case_id: int, n_results: int = 5) -> list[str]:
    """
    Queries ChromaDB for relevant document chunks for a given case.
    Returns a list of the most semantically relevant text chunks.
    """
    try:
        dyn_collection = chroma_client.get_or_create_collection(
            name="underwriting_docs",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
        results = dyn_collection.query(
            query_texts=[query],
            n_results=n_results,
            where={"case_id": str(case_id)}
        )
        
        docs = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        enriched_docs = []
        for doc, meta in zip(docs, metadatas):
            file_name = meta.get("file_name", "Unknown Document") if meta else "Unknown Document"
            enriched_docs.append(f"[Source Document: {file_name}]\n{doc}")
            
        return enriched_docs
    except Exception as e:
        print(f"[ChromaDB] Query error: {e}")
        return []

def store_rulebook(rulebook_id: int, text: str, metadata: dict = {}):
    """
    Chunks and stores rulebook text into ChromaDB under underwriting_rulebooks.
    Uses ~1000-character chunks with a small overlap for better context capture.
    """
    chunk_size = 1000
    overlap = 150
    chunks = []
    
    # Overlapping chunking
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += (chunk_size - overlap)

    if not chunks:
        return
        
    ids = [f"rb_{rulebook_id}_chunk_{i}" for i in range(len(chunks))]
    metas = [{**metadata, "rulebook_id": str(rulebook_id), "chunk": i} for i in range(len(chunks))]
    
    dyn_rulebook_collection = chroma_client.get_or_create_collection(
        name="underwriting_rulebooks",
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"}
    )
    dyn_rulebook_collection.upsert(
        documents=chunks,
        metadatas=metas,
        ids=ids
    )
    print(f"[ChromaDB] Stored {len(chunks)} chunks for rulebook_id={rulebook_id}")

def query_rulebook_context(query: str, n_results: int = 5, company_name: str = None, product_name: str = None) -> list[str]:
    """
    Queries ChromaDB for global underwriting guidelines related to the query.
    Filters by company_name and product_name if provided.
    """
    try:
        dyn_rulebook_collection = chroma_client.get_or_create_collection(
            name="underwriting_rulebooks",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )
        
        where_clause = None
        if company_name and product_name:
            where_clause = {"$and": [{"company_name": company_name}, {"product_name": product_name}]}
        elif company_name:
            where_clause = {"company_name": company_name}
        elif product_name:
            where_clause = {"product_name": product_name}
            
        if where_clause:
            results = dyn_rulebook_collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where_clause
            )
        else:
            results = dyn_rulebook_collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
        docs = results.get("documents", [[]])[0]
        return docs
    except Exception as e:
        print(f"[ChromaDB] Rulebook query error: {e}")
        return []
