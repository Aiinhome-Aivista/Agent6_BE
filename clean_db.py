import os
import shutil
from dotenv import load_dotenv

load_dotenv()

print("Starting full database cleanup...")

# 1. Clean MySQL Database
try:
    from database.connection import execute
    
    # Safe deletion order (child tables first, parent tables last)
    tables_to_delete = [
        "audit_logs",
        "case_mail_log",
        "ocr_extracted_data",
        "documents",
        "underwriting_decisions",
        "risk_assessments",
        "underwriting_cases",
        "rule_books"  # Added Knowledge Base table
    ]
    
    for table in tables_to_delete:
        execute(f"DELETE FROM {table}")
        print(f"Cleared MySQL table: {table}")
        
    print("MySQL cleanup complete.")
except Exception as e:
    print(f"MySQL cleanup error: {e}")

# 2. Clean ChromaDB
try:
    chroma_path = os.path.join(os.path.dirname(__file__), "chroma_store")
    if os.path.exists(chroma_path):
        # We delete the folder completely to ensure a fresh start
        # The backend will recreate it automatically on next run
        shutil.rmtree(chroma_path)
        print(f"Deleted ChromaDB directory: {chroma_path}")
    else:
        print("ChromaDB directory not found, skipping.")
except Exception as e:
    print(f"ChromaDB cleanup error: {e}")

# 3. Clean GraphDB (ArangoDB)
try:
    from arango import ArangoClient
    host = os.getenv("ARANGO_URL")
    db_name = os.getenv("ARANGO_DB")
    username = os.getenv("ARANGO_USER")
    password = os.getenv("ARANGO_PASSWORD")
    
    if host:
        client = ArangoClient(hosts=host)
        db = client.db(db_name, username=username, password=password)
        
        # Clear specific case entities
        if db.has_collection("entities"):
            db.collection("entities").truncate()
            print("Truncated ArangoDB collection: entities")
            
        if db.has_collection("relationships"):
            db.collection("relationships").truncate()
            print("Truncated ArangoDB collection: relationships")
            
        # Clear Knowledge Base entities
        if db.has_collection("kb_entities"):
            db.collection("kb_entities").truncate()
            print("Truncated ArangoDB collection: kb_entities")
            
        if db.has_collection("kb_relationships"):
            db.collection("kb_relationships").truncate()
            print("Truncated ArangoDB collection: kb_relationships")
            
        print("ArangoDB cleanup complete.")
    else:
        print("ArangoDB not configured in ENV, skipping.")
except Exception as e:
    print(f"ArangoDB cleanup error: {e}")

# 4. Clean Uploads folder
try:
    uploads_path = os.path.join(os.path.dirname(__file__), "uploads")
    if os.path.exists(uploads_path):
        for filename in os.listdir(uploads_path):
            file_path = os.path.join(uploads_path, filename)
            if os.path.isfile(file_path):
                os.unlink(file_path)
        print("Cleared uploads folder.")
except Exception as e:
    print(f"Uploads folder cleanup error: {e}")

# 5. Clean static_graphs folder
try:
    graphs_path = os.path.join(os.path.dirname(__file__), "static_graphs")
    if os.path.exists(graphs_path):
        for filename in os.listdir(graphs_path):
            file_path = os.path.join(graphs_path, filename)
            if os.path.isfile(file_path) and filename.endswith(".html"):
                os.unlink(file_path)
        print("Cleared HTML files from static_graphs folder.")
except Exception as e:
    print(f"static_graphs folder cleanup error: {e}")

print("--- Data Truncate Complete! ---")
