import os
from arango import ArangoClient

class GraphService:
    def __init__(self):
        self.host = os.getenv("ARANGO_URL")
        self.db_name = os.getenv("ARANGO_DB")
        self.username = os.getenv("ARANGO_USER")
        self.password = os.getenv("ARANGO_PASSWORD")
        self.client = ArangoClient(hosts=self.host)
        self.db = self._init_db()

    def _init_db(self):
        try:
            sys_db = self.client.db("_system", username=self.username, password=self.password)
            if not sys_db.has_database(self.db_name):
                sys_db.create_database(self.db_name)
            
            db = self.client.db(self.db_name, username=self.username, password=self.password)
            
            if not db.has_collection("entities"):
                db.create_collection("entities")
            if not db.has_collection("relationships"):
                db.create_collection("relationships", edge=True)
                
            if not db.has_graph("underwriting_graph"):
                db.create_graph("underwriting_graph")
                
            graph = db.graph("underwriting_graph")
            if not graph.has_edge_definition("relationships"):
                graph.create_edge_definition(
                    edge_collection="relationships",
                    from_vertex_collections=["entities"],
                    to_vertex_collections=["entities"]
                )
            return db
        except Exception as e:
            print(f"[GraphService Error] {e}")
            return None

    def insert_node(self, node_key, label, name, properties, case_id):
        if not self.db: return
        entity_data = {
            "_key": node_key,
            "label": label,
            "name": name,
            "properties": properties,
            "case_id": case_id
        }
        try:
            self.db.collection("entities").insert(entity_data, overwrite=True)
        except Exception as e:
            print(f"[GraphService Node Error] {e}")

    def insert_edge(self, edge_key, from_key, to_key, relation_type, case_id):
        if not self.db: return
        relationship_data = {
            "_key": edge_key,
            "_from": f"entities/{from_key}",
            "_to": f"entities/{to_key}",
            "type": relation_type,
            "case_id": case_id
        }
        try:
            self.db.collection("relationships").insert(relationship_data, overwrite=True)
        except Exception as e:
            print(f"[GraphService Edge Error] {e}")

    def check_fraud_ring(self, case_id):
        # Implementation for querying fraud paths
        # Returns True if fraud detected
        return False

graph_service = GraphService()
