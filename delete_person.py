import sys, os, sqlite3
sys.path.append("d:/Agent 6 - V1/API")
from database.connection import fetch_all, execute

# Find all Rahul Sharma cases
cases = fetch_all("SELECT id FROM underwriting_cases WHERE applicant_name LIKE %s", ('%rahul%',))
case_ids = [c['id'] for c in cases]
print(f"Found cases: {case_ids}")

for case_id in case_ids:
    # Get docs
    docs = fetch_all("SELECT file_name FROM documents WHERE case_id = %s", (case_id,))

    # Delete DB rows
    for sql in [
        "DELETE FROM ocr_extracted_data WHERE document_id IN (SELECT id FROM documents WHERE case_id = %s)",
        "DELETE FROM documents WHERE case_id = %s",
        "DELETE FROM case_mail_log WHERE case_id = %s",
        "DELETE FROM risk_assessments WHERE case_id = %s",
        "DELETE FROM underwriting_decisions WHERE case_id = %s",
        "DELETE FROM underwriting_cases WHERE id = %s",
    ]:
        try:
            execute(sql, (case_id,))
        except Exception as e:
            print(f"  Skip: {e}")
    print(f"  DB cleared for case_id={case_id}")

    # Delete upload files
    upload_dir = "d:/Agent 6 - V1/API/uploads"
    for doc in docs:
        p = os.path.join(upload_dir, doc['file_name'])
        if os.path.exists(p):
            os.remove(p)
            print(f"  Deleted upload: {doc['file_name']}")

    # Delete static graphs
    graph_dir = "d:/Agent 6 - V1/API/static_graphs"
    for f in os.listdir(graph_dir):
        if f"case_{case_id}" in f or f"case{case_id}" in f or "rahul" in f.lower():
            os.remove(os.path.join(graph_dir, f))
            print(f"  Deleted graph: {f}")

    # ChromaDB - delete by case_id
    chroma_db = "d:/Agent 6 - V1/API/chroma_store/chroma.sqlite3"
    conn = sqlite3.connect(chroma_db)
    cur = conn.cursor()
    cur.execute("SELECT id FROM embedding_metadata WHERE key='case_id' AND string_value=?", (str(case_id),))
    ids = [r[0] for r in cur.fetchall()]
    if ids:
        placeholders = ",".join("?" * len(ids))
        cur.execute(f"DELETE FROM embedding_metadata WHERE id IN ({placeholders})", ids)
        cur.execute(f"DELETE FROM embeddings WHERE id IN ({placeholders})", ids)
        conn.commit()
        print(f"  Deleted {len(ids)} chroma embeddings for case_id={case_id}")
    conn.close()

# ArangoDB
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
            cursor = db.aql.execute(
                f"FOR v IN {col_name} FILTER v.case_id IN @ids RETURN v._id",
                bind_vars={"ids": case_ids}
            )
            arango_ids = [d for d in cursor]
            col_obj = db.collection(col_name)
            for _id in arango_ids:
                try: col_obj.delete(_id)
                except: pass
            print(f"  ArangoDB [{col_name}]: deleted {len(arango_ids)} items")
except Exception as e:
    print(f"  ArangoDB error: {e}")

print("DONE - Rahul Sharma data deleted.")
