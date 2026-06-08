"""
Unified GraphRAG Pipeline Service
Integrates:
  1. OCR text extraction (reused from services.ocr_service)
  2. LLM Raw Summary Generation (reused Mistral AI client config)
  3. ChromaDB Vector Store indexing (reused from services.vector_store)
  4. ArangoDB Cloud Knowledge Graph extraction and storage
"""
import os
import json
import re
from arango import ArangoClient
from services.vector_store import chroma_client
from services.ocr_service import extract_text

# Load environment variables
ARANGO_HOST = os.getenv("ARANGO_URL")
ARANGO_DB = os.getenv("ARANGO_DB")
ARANGO_USERNAME = os.getenv("ARANGO_USER")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD")

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
MISTRAL_MODEL = os.getenv("MISTRAL_LOCAL_MODEL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_MODEL")

class GraphRagPipeline:
    def __init__(self):
        # 1. Initialize ArangoDB Cloud Client
        self.client = ArangoClient(hosts=ARANGO_HOST)
        self.db = self._init_arango_db()
        # 2. Reuse standard ChromaDB collection dynamically to avoid stale IDs
        from services.vector_store import ef
        self.collection = chroma_client.get_or_create_collection(
            name="underwriting_docs",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"}
        )

    def _init_arango_db(self):
        """Initializes database and graph collections on ArangoDB Cloud if they do not exist."""
        try:
            sys_db = self.client.db("_system", username=ARANGO_USERNAME, password=ARANGO_PASSWORD)
            if not sys_db.has_database(ARANGO_DB):
                sys_db.create_database(ARANGO_DB)
                
            db = self.client.db(ARANGO_DB, username=ARANGO_USERNAME, password=ARANGO_PASSWORD)
            
            # Create standard collections
            if not db.has_collection("entities"):
                db.create_collection("entities")
                
            if not db.has_collection("relationships"):
                db.create_collection("relationships", edge=True)
                
            # Create graph definition
            if not db.has_graph("underwriting_graph"):
                db.create_graph("underwriting_graph")
                
            graph = db.graph("underwriting_graph")
            if not graph.has_edge_definition("relationships"):
                graph.create_edge_definition(
                    edge_collection="relationships",
                    from_vertex_collections=["entities"],
                    to_vertex_collections=["entities"]
                )
            print("[ArangoDB] Successfully connected and initialized Graph Collections.")
            return db
        except Exception as e:
            print(f"[ArangoDB Init Error] Failed to connect/initialize ArangoDB: {e}")
            return None

    async def call_llm_api(self, prompt: str) -> str:
        """Helper to call Mistral AI following risk_engine's exact paradigm."""
        if not MISTRAL_API_KEY or MISTRAL_API_KEY == "your_mistral_key_here":
            return "{}"
            
        try:
            from mistralai.client import MistralClient
            from mistralai.models.chat_completion import ChatMessage
            
            kwargs = {"api_key": MISTRAL_API_KEY, "timeout": 300}
            if os.getenv("MISTRAL_MODE") == "Local":
                kwargs["endpoint"] = os.getenv("MISTRAL_LOCAL_URL")
            client = MistralClient(**kwargs)
            response = client.chat(
                model=MISTRAL_MODEL,
                messages=[ChatMessage(role="user", content=prompt)],
                response_format={"type": "json_object"} if "json" in prompt.lower() else None,
                temperature=0.1
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[GraphRag LLM Error] {e}")
            return "{}"

    async def process_document_flow(self, case_id: int, file_path: str, file_name: str) -> dict:
        """
        Runs the integrated GraphRAG pipeline in exact requested order:
        1. Read OCR text.
        2. Generate raw summary using LLM.
        3. Extract nodes/edges using LLM and push to ArangoDB Cloud FIRST.
        4. Index raw text, summary, and relationship sentences into ChromaDB SECOND.
        """
        # Step 1: Read extracted text
        raw_text = extract_text(file_path)
        if not raw_text:
            raise Exception("No text content could be extracted from this document.")

        # Step 2: Generate Raw Summary via LLM
        print(f"[GraphRAG Pipeline] Generating raw summary for case {case_id}...")
        prompt_summary = f"""You are an Expert Health Underwriting Assistant.
Please review this clinical case / medical report and provide a detailed raw summary.
Highlight patient parameters, symptoms, chronic illnesses, diagnostic measurements, and treatments.

DOCUMENT CONTENT:
{raw_text[:12000]}
"""
        raw_summary = await self.call_llm_api(prompt_summary)
        if not raw_summary or raw_summary == "{}":
            # Fallback if LLM fails or is unconfigured
            raw_summary = f"Automatic summary of {file_name}. Extracted character count: {len(raw_text)}."

        # Step 3: Extract Nodes and Edges from summary FIRST (GRAPH DB)
        print(f"[GraphRAG Pipeline] [GRAPH FIRST] Extracting Graph entities and relationships...")
        prompt_graph = f"""
        Analyze this underwriting summary and extract key entities (Nodes) and relationships (Edges).
        Nodes can be: Patient, Disease, Medicine, Policy, Metric, Rule.
        Edges can be: HAS_DISEASE, TAKES_MEDICINE, MEASURED_VALUE, VIOLATES, APPLIED_FOR.

        Strictly output a JSON object in this format (no markdown, no wrappers):
        {{
          "nodes": [
            {{"id": "PatientName", "label": "Patient", "properties": {{"age": 45, "gender": "Male"}}}},
            {{"id": "Hypertension", "label": "Disease", "properties": {{"severity": "severe"}}}},
            {{"id": "Amlodipine", "label": "Medicine", "properties": {{"dosage": "5mg"}}}}
          ],
          "edges": [
            {{"from_id": "PatientName", "to_id": "Hypertension", "type": "HAS_DISEASE"}},
            {{"from_id": "PatientName", "to_id": "Amlodipine", "type": "TAKES_MEDICINE"}}
          ]
        }}

        TEXT SUMMARY:
        {raw_summary}
        """
        graph_json_str = await self.call_llm_api(prompt_graph)
        
        # Parse JSON safely
        graph_data = {"nodes": [], "edges": []}
        try:
            # Clean possible markdown wrappers if LLM returned them
            cleaned_json = graph_json_str.strip()
            if cleaned_json.startswith("```"):
                cleaned_json = cleaned_json.split("\n", 1)[-1]
            if cleaned_json.endswith("```"):
                cleaned_json = cleaned_json.rsplit("\n", 1)[0]
            if cleaned_json.startswith("json"):
                cleaned_json = cleaned_json[4:].strip()
            
            graph_data = json.loads(cleaned_json)
        except Exception as json_err:
            print(f"[GraphRAG Pipeline] JSON parsing failed: {json_err}. Using empty graph.")

        # Step 4: Push to ArangoDB Cloud FIRST (GRAPH DB)
        nodes_inserted = 0
        edges_inserted = 0
        
        if self.db:
            print(f"[ArangoDB] Pushing {len(graph_data.get('nodes', []))} nodes to Cloud...")
            # Save nodes
            for node in graph_data.get("nodes", []):
                safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(node['id']).replace(' ', '_'))
                node_key = f"case_{case_id}_{safe_id}"
                entity_data = {
                    "_key": node_key,
                    "label": node["label"],
                    "name": node["id"],
                    "properties": node.get("properties", {}),
                    "case_id": case_id
                }
                self.db.collection("entities").insert(entity_data, overwrite=True)
                nodes_inserted += 1

            # Save edges
            print(f"[ArangoDB] Pushing {len(graph_data.get('edges', []))} edges to Cloud...")
            for edge in graph_data.get("edges", []):
                safe_from = re.sub(r'[^a-zA-Z0-9_-]', '', str(edge['from_id']).replace(' ', '_'))
                safe_to = re.sub(r'[^a-zA-Z0-9_-]', '', str(edge['to_id']).replace(' ', '_'))
                from_key = f"entities/case_{case_id}_{safe_from}"
                to_key = f"entities/case_{case_id}_{safe_to}"
                edge_key = f"edge_{case_id}_{safe_from}_{safe_to}"
                
                relationship_data = {
                    "_key": edge_key,
                    "_from": from_key,
                    "_to": to_key,
                    "type": edge["type"],
                    "case_id": case_id
                }
                try:
                    self.db.collection("relationships").insert(relationship_data, overwrite=True)
                    edges_inserted += 1
                except Exception as edge_err:
                    print(f"[ArangoDB Edge Error] Could not connect nodes: {edge_err}")

        # Step 5: Push original text AND raw summary to ChromaDB SECOND (VECTOR DB)
        print(f"[ChromaDB] [VECTOR SECOND] Indexing original text and summary...")
        combined_text = f"RAW SUMMARY:\n{raw_summary}\n\nFULL DOCUMENT TEXT:\n{raw_text}"
        
        # Simple chunking to prevent embedding size issues
        chunk_size = 1000
        chunks = [combined_text[i:i+chunk_size] for i in range(0, len(combined_text), chunk_size)]
        
        ids = [f"case_{case_id}_chunk_{i}" for i in range(len(chunks))]
        metas = [{"case_id": str(case_id), "file_name": file_name, "type": "consolidated", "chunk": i} for i in range(len(chunks))]
        
        self.collection.upsert(
            documents=chunks,
            metadatas=metas,
            ids=ids
        )

        # Step 6: Double-Index relationships back into ChromaDB SECOND (VECTOR DB)
        print(f"[ChromaDB] [VECTOR SECOND] Double-indexing relationships...")
        relationship_sentences = []
        
        # Build sentences for nodes
        for node in graph_data.get("nodes", []):
            properties_str = ", ".join([f"{k}: {v}" for k, v in node.get("properties", {}).items() if v is not None])
            properties_str = f" ({properties_str})" if properties_str else ""
            relationship_sentences.append(
                f"Entity Profile: Patient ID case_{case_id}_{node['id']} is a {node['label']} named {node['id']}{properties_str}."
            )
            
        # Build sentences for edges
        for edge in graph_data.get("edges", []):
            relationship_sentences.append(
                f"Relationship: {edge['from_id']} has relation {edge['type']} with {edge['to_id']} in case {case_id}."
            )
            
        if relationship_sentences:
            rel_ids = [f"case_{case_id}_rel_{idx}" for idx in range(len(relationship_sentences))]
            rel_metas = [{"case_id": str(case_id), "file_name": file_name, "type": "relationship", "idx": idx} for idx in range(len(relationship_sentences))]
            self.collection.upsert(
                documents=relationship_sentences,
                metadatas=rel_metas,
                ids=rel_ids
            )
            print(f"[ChromaDB] Stored {len(relationship_sentences)} relationship semantic chunks.")

        # Generate local interactive HTML graph for the user to view locally
        try:
            self._generate_local_html_graph(case_id, file_name, graph_data)
        except Exception as html_err:
            print(f"[GraphRAG HTML Generator Error] {html_err}")

        return {
            "status": "success",
            "summary": raw_summary,
            "nodes_count": nodes_inserted,
            "edges_count": edges_inserted,
            "relationships_vectorized": len(relationship_sentences)
        }

    def _generate_local_html_graph(self, case_id: int, file_name: str, graph_data: dict):
        """Generates an interactive, self-contained HTML graph file using Vis.js for local viewing."""
        import os
        static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static_graphs")
        os.makedirs(static_dir, exist_ok=True)
        
        # Color mapping for node styling
        color_map = {
            "Patient": "#3b82f6",     # Blue
            "Disease": "#ef4444",     # Red
            "Medicine": "#10b981",    # Green
            "Metric": "#f59e0b",      # Amber
            "Policy": "#8b5cf6",      # Purple
            "Rule": "#8b5cf6"         # Purple
        }
        
        vis_nodes = []
        for node in graph_data.get("nodes", []):
            node_type = node.get("label", "Node")
            color = color_map.get(node_type, "#64748b")
            props = node.get("properties", {})
            properties_str = "<br>".join([f"<b>{k}</b>: {v}" for k, v in props.items() if v is not None])
            title = f"<b>Type:</b> {node_type}<br>{properties_str}" if properties_str else f"<b>Type:</b> {node_type}"
            
            vis_nodes.append({
                "id": node["id"],
                "label": node["id"],
                "title": title,
                "color": color
            })
            
        vis_edges = []
        for edge in graph_data.get("edges", []):
            vis_edges.append({
                "from": edge["from_id"],
                "to": edge["to_id"],
                "label": edge["type"]
            })
            
        # Complete interactive HTML template
        html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Interactive Knowledge Graph - Case {case_id}</title>
    <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    <style type="text/css">
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #0f172a;
            color: #f1f5f9;
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }}
        #header {{
            padding: 20px;
            background-color: #1e293b;
            border-bottom: 2px solid #334155;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        #header h1 {{ margin: 0; font-size: 24px; color: #38bdf8; }}
        #header p {{ margin: 5px 0 0 0; font-size: 14px; color: #94a3b8; }}
        #network {{
            width: 100%;
            height: calc(100vh - 82px);
            background-color: #0f172a;
        }}
        #legend {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            background-color: rgba(30, 41, 59, 0.9);
            border: 1px solid #475569;
            border-radius: 8px;
            padding: 15px;
            color: #f1f5f9;
            font-size: 12px;
            z-index: 100;
        }}
        .legend-item {{ display: flex; align-items: center; margin-bottom: 5px; }}
        .legend-color {{ width: 12px; height: 12px; border-radius: 50%; margin-right: 8px; }}
    </style>
</head>
<body>
    <div id="header">
        <div>
            <h1>Intelligent Underwriting Knowledge Graph</h1>
            <p>Case ID: {case_id} | Document Source: {file_name}</p>
        </div>
        <div style="font-size: 14px; color: #38bdf8; font-weight: bold; background: rgba(56,189,248,0.1); padding: 5px 12px; border-radius: 20px;">
            GraphRAG Unified Node & Edge Map
        </div>
    </div>
    <div id="network"></div>
    
    <div id="legend">
        <h3 style="margin-top: 0; margin-bottom: 10px; font-size: 14px; color: #38bdf8;">Graph Legend</h3>
        <div class="legend-item"><div class="legend-color" style="background-color: #3b82f6;"></div>Patient</div>
        <div class="legend-item"><div class="legend-color" style="background-color: #ef4444;"></div>Disease</div>
        <div class="legend-item"><div class="legend-color" style="background-color: #10b981;"></div>Medicine</div>
        <div class="legend-item"><div class="legend-color" style="background-color: #f59e0b;"></div>Metric</div>
        <div class="legend-item"><div class="legend-color" style="background-color: #8b5cf6;"></div>Policy / Rule</div>
    </div>

    <script type="text/javascript">
        var nodes = new vis.DataSet({json.dumps(vis_nodes)});
        var edges = new vis.DataSet({json.dumps(vis_edges)});

        var container = document.getElementById('network');
        var data = {{
            nodes: nodes,
            edges: edges
        }};
        var options = {{
            nodes: {{
                shape: 'dot',
                size: 26,
                font: {{ size: 15, color: '#f1f5f9', face: 'Outfit, Inter, sans-serif', strokeWidth: 4, strokeColor: '#0f172a' }},
                borderWidth: 2,
                shadow: true
            }},
            edges: {{
                width: 2,
                font: {{ size: 11, color: '#cbd5e1', face: 'Outfit, Inter, sans-serif', strokeWidth: 3, strokeColor: '#0f172a', align: 'horizontal' }},
                color: {{ color: '#475569', highlight: '#38bdf8', hover: '#38bdf8' }},
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.8 }} }},
                smooth: {{ type: 'cubicBezier', forceDirection: 'none', roundness: 0.5 }}
            }},
            physics: {{
                forceAtlas2Based: {{
                    gravitationalConstant: -70,
                    centralGravity: 0.005,
                    springLength: 180,
                    springConstant: 0.08
                }},
                solver: 'forceAtlas2Based',
                stabilization: {{ iterations: 200 }}
            }},
            interaction: {{ hover: true, tooltipDelay: 200 }}
        }};
        var network = new vis.Network(container, data, options);
    </script>
</body>
</html>
"""
        html_file = os.path.join(static_dir, f"case_{case_id}_graph.html")
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_template)
        print(f"[GraphRAG HTML Generator] Successfully saved interactive local graph to: {html_file}")
