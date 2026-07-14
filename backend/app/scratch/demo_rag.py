import uuid
from typing import List, Dict, Any
import numpy as np

# Ground truth knowledge base documents
DOCUMENTS = {
    "benefits.txt": "Employee health insurance covers 100% of dental and vision checkups. Mental health counseling has a copay of $10 per session.",
    "it_security.txt": "All employees must enable multi-factor authentication (MFA) on their accounts. Passwords must be at least 16 characters long and changed every 90 days.",
    "travel_policy.txt": "For business travel, meals are reimbursed up to $75 per day. Standard class flights must be booked at least 14 days in advance."
}

# Vocabulary for term-based mock vector representations
VOCAB = ["health", "dental", "insurance", "vision", "password", "mfa", "security", "travel", "meals", "reimbursed", "flights", "vision"]

def get_mock_vector(text: str) -> List[float]:
    """Generates a normalized mock embedding vector based on vocabulary frequency."""
    text_lower = text.lower()
    vector = np.zeros(1024)
    for idx, term in enumerate(VOCAB):
        if term in text_lower:
            vector[idx] = 1.0
    # Normalize vector to simulate standard embedding unit vectors
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector.tolist()

def mock_search_similar(query: str) -> List[Dict[str, Any]]:
    """Simulates Qdrant search by computing cosine similarity over seeded chunks."""
    query_vec = np.array(get_mock_vector(query))
    results = []
    
    for filename, content in DOCUMENTS.items():
        doc_vec = np.array(get_mock_vector(content))
        # Cosine similarity for normalized vectors is just the dot product
        score = float(np.dot(query_vec, doc_vec))
        
        results.append({
            "document_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, filename)),
            "filename": filename,
            "text": content,
            "page_number": 1,
            "section": "General Policy",
            "score": score
        })
        
    # Sort by score descending
    results.sort(key=lambda x: float(str(x["score"])), reverse=True)
    return results

def mock_generate_answer(query: str, retrieved: List[Dict[str, Any]]) -> str:
    """A rule-based mock LLM that generates a grounded answer directly from context."""
    query_lower = query.lower()
    
    # Check context documents
    context_map = {r["filename"]: r["text"] for r in retrieved}
    
    if "health" in query_lower or "insurance" in query_lower or "dental" in query_lower or "vision" in query_lower:
        if "benefits.txt" in context_map:
            return "Based on company benefits [1], employee health insurance covers 100% of dental and vision checkups, with a $10 copay for mental health counseling."
    
    if "password" in query_lower or "security" in query_lower or "mfa" in query_lower:
        if "it_security.txt" in context_map:
            return "Per IT security guidelines [1], all accounts must have MFA enabled, and passwords must be at least 16 characters long and rotated every 90 days."
            
    if "travel" in query_lower or "meals" in query_lower or "flight" in query_lower:
        if "travel_policy.txt" in context_map:
            return "According to the travel policy [1], meals are reimbursed up to $75/day, and standard flights must be booked at least 14 days in advance."
            
    return "not enough information in the knowledge base"

def run_rag_query(question: str) -> Dict[str, Any]:
    """Runs a simulated end-to-end RAG query."""
    threshold = 0.35
    
    # 1. Retrieve
    retrieved = mock_search_similar(question)
    
    # 2. Filter by threshold
    relevant = [r for r in retrieved if r["score"] >= threshold]
    
    if not relevant:
        return {
            "question": question,
            "answer": "not enough information in the knowledge base",
            "citations": [],
            "retrieved_chunk_count": 0
        }
        
    # 3. Generate grounded answer
    answer = mock_generate_answer(question, relevant)
    
    # 4. Format citations
    citations = []
    for r in relevant:
        citations.append({
            "document_id": r["document_id"],
            "filename": r["filename"],
            "page_or_section": r["section"],
            "chunk_text_snippet": r["text"]
        })
        
    return {
        "question": question,
        "answer": answer,
        "citations": citations,
        "retrieved_chunk_count": len(relevant)
    }

if __name__ == "__main__":
    test_questions = [
        "What does the health insurance cover?",
        "What are the rules for passwords?",
        "How much is reimbursed for meals during business travel?",
        "What is the policy for company cars?"
    ]
    
    print("=== ENTERPRISERAG BASELINE RAG SIMULATION ===")
    for q in test_questions:
        print(f"\nQuestion: {q}")
        res = run_rag_query(q)
        print(f"Answer  : {res['answer']}")
        print(f"Citations Count: {len(res['citations'])}")
        for idx, cit in enumerate(res['citations']):
            print(f"  [{idx+1}] Doc: {cit['filename']} | Location: {cit['page_or_section']}")
            print(f"      Snippet: {cit['chunk_text_snippet']}")
