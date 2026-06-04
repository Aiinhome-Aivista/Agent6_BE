import sqlite3

db_path = r"d:\Agent 6 - V1\API\chroma_store\chroma.sqlite3"
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Get IDs of embeddings that have case_id = 1 or 2 in metadata
cur.execute("SELECT id FROM embedding_metadata WHERE key='case_id' AND string_value IN ('1', '2')")
rows = cur.fetchall()
ids = [r[0] for r in rows]
print(f"Chroma embedding rows for Saikat cases: {len(ids)}")

if ids:
    placeholders = ",".join("?" * len(ids))
    # Delete from embedding_metadata
    cur.execute(f"DELETE FROM embedding_metadata WHERE id IN ({placeholders})", ids)
    # Delete from embeddings (same id is the foreign key)
    cur.execute(f"DELETE FROM embeddings WHERE id IN ({placeholders})", ids)
    conn.commit()
    print(f"Deleted {len(ids)} chroma embedding entries")
else:
    print("No chroma entries found for case_id 1 or 2")

# Verify
cur.execute("SELECT COUNT(*) FROM embeddings")
print(f"Remaining embeddings in chroma: {cur.fetchone()[0]}")

conn.close()
print("Chroma cleanup DONE")
