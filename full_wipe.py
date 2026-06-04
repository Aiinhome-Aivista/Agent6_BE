import sys, os, sqlite3

sys.path.append("d:/Agent 6 - V1/API")
from database.connection import execute, fetch_all

print("=" * 50)
print("STEP 1: Clearing MySQL tables...")
print("=" * 50)

# Order matters due to foreign keys
tables_to_clear = [
    "ocr_extracted_data",
    "documents",
    "case_mail_log",
    "audit_logs",
    "risk_assessments",
    "underwriting_decisions",
    "customer_claims",
    "uploaded_csv_records",
    "underwriting_cases",
]

for table in tables_to_clear:
    try:
        execute(f"DELETE FROM `{table}`", ())
        print(f"  Cleared: {table}")
    except Exception as e:
        print(f"  Error clearing {table}: {e}")

print()
print("=" * 50)
print("STEP 2: Clearing Uploads folder...")
print("=" * 50)

upload_dir = "d:/Agent 6 - V1/API/uploads"
deleted = []
if os.path.exists(upload_dir):
    for f in os.listdir(upload_dir):
        try:
            os.remove(os.path.join(upload_dir, f))
            deleted.append(f)
        except Exception as e:
            print(f"  Error deleting {f}: {e}")
print(f"  Deleted {len(deleted)} upload files")

print()
print("=" * 50)
print("STEP 3: Clearing Static Graphs...")
print("=" * 50)

graph_dir = "d:/Agent 6 - V1/API/static_graphs"
g_deleted = []
if os.path.exists(graph_dir):
    for f in os.listdir(graph_dir):
        try:
            os.remove(os.path.join(graph_dir, f))
            g_deleted.append(f)
        except Exception as e:
            print(f"  Error deleting {f}: {e}")
print(f"  Deleted {len(g_deleted)} graph files")

print()
print("=" * 50)
print("STEP 4: Clearing ChromaDB (all embeddings)...")
print("=" * 50)

chroma_db = "d:/Agent 6 - V1/API/chroma_store/chroma.sqlite3"
try:
    conn = sqlite3.connect(chroma_db)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM embeddings")
    before = cur.fetchone()[0]
    cur.execute("DELETE FROM embedding_metadata")
    cur.execute("DELETE FROM embeddings")
    cur.execute("DELETE FROM embedding_fulltext_search")
    conn.commit()
    conn.close()
    print(f"  Deleted {before} chroma embeddings")
except Exception as e:
    print(f"  Chroma error: {e}")

print()
print("=" * 50)
print("STEP 5: Clearing ArangoDB...")
print("=" * 50)

try:
    from arango import ArangoClient
    arango_client = ArangoClient(hosts=os.getenv("ARANGO_HOST", "https://a71fd1666bd9.arangodb.cloud:8529"))
    db = arango_client.db(
        os.getenv("ARANGO_DB", "underwriting_db"),
        username=os.getenv("ARANGO_USERNAME", "root"),
        password=os.getenv("ARANGO_PASSWORD", "TnHBO0Y4FwKptmr6GxrL")
    )
    for col_name in ["entities", "relationships"]:
        if db.has_collection(col_name):
            result = db.collection(col_name).truncate()
            print(f"  Truncated arango collection: {col_name}")
        else:
            print(f"  Arango [{col_name}]: not found")
    print("  ArangoDB DONE")
except Exception as e:
    print(f"  ArangoDB error: {e}")

print()
print("=" * 50)
print("ALL DONE - Full wipe complete!")
print("=" * 50)
