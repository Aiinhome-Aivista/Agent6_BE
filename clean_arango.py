import os, sys
sys.path.append("d:/Agent 6 - V1/API")

try:
    from arango import ArangoClient
    arango_client = ArangoClient(hosts=os.getenv("ARANGO_HOST", "https://a71fd1666bd9.arangodb.cloud:8529"))
    db = arango_client.db(
        os.getenv("ARANGO_DB", "underwriting_db"),
        username=os.getenv("ARANGO_USERNAME", "root"),
        password=os.getenv("ARANGO_PASSWORD", "TnHBO0Y4FwKptmr6GxrL")
    )

    collections_to_clean = ["entities", "relationships", "nodes", "edges"]
    for col_name in collections_to_clean:
        if db.has_collection(col_name):
            cursor = db.aql.execute(
                f"FOR v IN {col_name} FILTER v.case_id IN [1, 2] RETURN v._id"
            )
            ids = [d for d in cursor]
            col_obj = db.collection(col_name)
            for _id in ids:
                try:
                    col_obj.delete(_id)
                except Exception as e:
                    print(f"  Error deleting {_id}: {e}")
            print(f"Arango [{col_name}]: deleted {len(ids)} items")
        else:
            print(f"Arango [{col_name}]: collection not found")

    print("ArangoDB cleanup DONE")
except Exception as e:
    print(f"ArangoDB error: {e}")
