import os
import json

class DocumentValidator:
    """
    Document Validation Agent
    Validates uploaded documents against mandatory requirements using Mistral LLM.
    """
    def __init__(self):
        self.name = "Document Validator"

    async def validate_documents(self, combined_text: str, application_type: str) -> dict:
        print(f"[{self.name}] Validating uploaded documents for {application_type}")
        
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        MISTRAL_MODEL = os.getenv("MISTRAL_LOCAL_MODEL") if os.getenv("MISTRAL_MODE") == "Local" else os.getenv("MISTRAL_MODEL")
        
        if not MISTRAL_API_KEY or MISTRAL_API_KEY == "your_mistral_key_here":
             print(f"[{self.name}] MISTRAL_API_KEY not found. Skipping validation.")
             return {"missing": []}
             
        try:
            from mistralai.client import MistralClient
            from mistralai.models.chat_completion import ChatMessage
            
            if application_type == "New Policy":
                docs_requirements = """
Mandatory documents for New Policy Application:
1. Identity Proof (Aadhaar Card OR PAN Card)
2. Medical Reports
3. Bank Statement
4. Previous Claim History
"""
            else:
                docs_requirements = """
Mandatory documents for Existing Claim / Existing Policy:
1. Identity Proof (Aadhaar Card OR PAN Card)
2. Policy Document / Existing Policy PDF
3. Claim Form
4. Hospital Bills
5. Discharge Summary
6. Medical Reports / Prescriptions
7. Previous Claim History
"""
            prompt = f"""You are an Enterprise Insurance Underwriting AI Assistant.
Validate the following documents against the STRICT requirements.
{docs_requirements}

TEXT EXTRACTED FROM UPLOADS:
{combined_text[:5000]}

CRITICAL INSTRUCTION: You MUST cross-check every single mandatory document from the list above against the extracted text. If a mandatory document (like Bank Statement or Claim Form) is NOT found in the text, you MUST include it in the "missing_documents" array. DO NOT skip any mandatory document. If the list contains 2 items and you only find 1, the other MUST be in "missing_documents" and validation_status MUST be "failed".

Return STRICT JSON format:
{{
  "validation_status": "success | failed",
  "missing_documents": ["List", "of", "missing", "docs"],
  "summary": "Short explanation"
}}
"""
            kwargs = {"api_key": MISTRAL_API_KEY, "timeout": 60}
            if os.getenv("MISTRAL_MODE") == "Local":
                kwargs["endpoint"] = os.getenv("MISTRAL_LOCAL_URL")
            client = MistralClient(**kwargs)
            response = client.chat(
                model=MISTRAL_MODEL,
                messages=[ChatMessage(role="user", content=prompt)],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            reply = response.choices[0].message.content.strip()
            
            # Clean JSON markdown blocks if any
            if reply.startswith("```json"): reply = reply[7:-3].strip()
            elif reply.startswith("```"): reply = reply[3:-3].strip()
            
            parsed_result = json.loads(reply)
            return {
                "missing": parsed_result.get("missing_documents", []),
                "raw_validation": parsed_result
            }
            
        except Exception as e:
            print(f"[{self.name}] Validation Error: {e}")
            return {"missing": []}

validator = DocumentValidator()
