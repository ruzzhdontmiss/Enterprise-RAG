import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document
from app.models.chat_message import ChatMessage
from app.core.auth import create_access_token

client = TestClient(app)


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_query_returns_citations_from_retrieved_chunks(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that query returns the answer along with structured citations from retrieved chunks."""
    tenant = Tenant(id=uuid.uuid4(), name="Acme RAG")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="query_user@acme.com",
        hashed_password="hashed_password",
        role="member",
    )
    db_session.add(user)
    db_session.commit()
    
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        filename="company_policy.pdf",
        status="ready",
    )
    db_session.add(doc)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    # Mock embeddings
    mock_embed.return_value = [[0.1] * 1024]
    
    # Mock Qdrant results
    mock_search.return_value = [
        {
            "id": "point-1",
            "score": 0.85,
            "text": "The standard policy allows up to 25 vacation days.",
            "page_number": 3,
            "section": "Vacation and Time-Off",
            "document_id": str(doc.id),
        }
    ]
    mock_scroll.return_value = ([], None)
    
    # Mock rerank to return high score
    mock_rerank.side_effect = lambda q, chunks: [dict(c, rerank_score=0.85) for c in chunks]
    
    # Mock LLM generation response
    mock_generate.return_value = "Employees are allowed up to 25 vacation days based on company policy [1]."

    response = client.post("/query", json={"question": "how many vacation days do I get?"}, headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert "answer" in data
    assert "citations" in data
    assert data["retrieved_chunk_count"] == 1
    assert data["answer"] == "Employees are allowed up to 25 vacation days based on company policy [1]."
    
    # Check citations contents
    citations = data["citations"]
    assert len(citations) == 1
    assert citations[0]["document_id"] == str(doc.id)
    assert citations[0]["filename"] == "company_policy.pdf"
    assert "Vacation and Time-Off" in citations[0]["page_or_section"]
    assert citations[0]["chunk_text_snippet"] == "The standard policy allows up to 25 vacation days."


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_query_with_no_matching_chunks_returns_no_info_response(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that query returns the fallback message and skips LLM generation if no chunks exceed similarity threshold."""
    tenant = Tenant(id=uuid.uuid4(), name="Acme RAG")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="query_user@acme.com",
        hashed_password="hashed_password",
        role="member",
    )
    db_session.add(user)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    # Mock embeddings
    mock_embed.return_value = [[0.1] * 1024]
    
    # Mock Qdrant results
    mock_search.return_value = [
        {
            "id": "point-1",
            "score": 0.20,
            "text": "Unrelated text snippet.",
            "page_number": 1,
            "section": "None",
            "document_id": str(uuid.uuid4()),
        }
    ]
    mock_scroll.return_value = ([], None)
    
    # Mock rerank to return low score
    mock_rerank.side_effect = lambda q, chunks: [dict(c, rerank_score=0.1) for c in chunks]

    response = client.post("/query", json={"question": "how many vacation days do I get?"}, headers=headers)
    assert response.status_code == 200
    
    data = response.json()
    assert data["answer"] == "not enough information in the knowledge base"
    assert len(data["citations"]) == 0
    assert data["retrieved_chunk_count"] == 0
    
    # Assert that generate_answer was only called once (for query rewrite) and skipped for generation
    assert mock_generate.call_count == 1


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_query_is_tenant_scoped(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that query strictly filters by the user's active tenant_id."""
    tenant_a = Tenant(id=uuid.uuid4(), name="Tenant A")
    tenant_b = Tenant(id=uuid.uuid4(), name="Tenant B")
    db_session.add_all([tenant_a, tenant_b])
    db_session.commit()
    
    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="a@tenant.com",
        hashed_password="pwd",
        role="member",
    )
    db_session.add(user_a)
    db_session.commit()

    token = create_access_token(user_id=user_a.id, tenant_id=tenant_a.id, role=user_a.role)
    headers = {"Authorization": f"Bearer {token}"}

    # Mock embeddings and search
    mock_embed.return_value = [[0.1] * 1024]
    mock_search.return_value = []
    mock_scroll.return_value = ([], None)
    mock_rerank.side_effect = lambda q, chunks: chunks

    client.post("/query", json={"question": "hello?"}, headers=headers)
    
    # Assert that QdrantVectorStore.search_similar was called using Tenant A's id, not B
    assert mock_search.called
    call_args = mock_search.call_args[1]
    assert call_args["tenant_id"] == tenant_a.id
    assert call_args["tenant_id"] != tenant_b.id


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_chat_message_persisted_with_correct_tenant_id(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that each query event is persisted to the ChatMessage database table with correct mapping."""
    tenant = Tenant(id=uuid.uuid4(), name="Chat Log Org")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="chat_user@org.com",
        hashed_password="pwd",
        role="member",
    )
    db_session.add(user)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    mock_embed.return_value = [[0.1] * 1024]
    mock_search.return_value = []
    mock_scroll.return_value = ([], None)
    mock_rerank.side_effect = lambda q, chunks: chunks
    
    # Execute query
    client.post("/query", json={"question": "What is life?"}, headers=headers)
    
    # Retrieve messages directly from DB
    messages = db_session.query(ChatMessage).all()
    assert len(messages) == 1
    
    msg = messages[0]
    assert msg.tenant_id == tenant.id
    assert msg.user_id == user.id
    assert msg.question == "What is life?"
    assert msg.answer == "not enough information in the knowledge base"
    assert msg.citations_json == []


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_query_stream_returns_sse_events(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that POST /query/stream successfully responds with an SSE token stream."""
    tenant = Tenant(id=uuid.uuid4(), name="Stream Org")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="stream_user@org.com",
        hashed_password="pwd",
        role="member",
    )
    db_session.add(user)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    mock_embed.return_value = [[0.1] * 1024]
    mock_search.return_value = [{
        "document_id": str(uuid.uuid4()),
        "text": "Highly relevant chunk text",
        "page_number": 1,
        "section": "Sec",
        "score": 0.85,
    }]
    mock_scroll.return_value = ([], None)
    mock_rerank.side_effect = lambda q, chunks: [dict(c, rerank_score=0.85) for c in chunks]

    with patch("app.core.llm_provider.MistralLlmProvider.generate_answer_stream", return_value=iter(["mocked ", "streamed ", "answer"])):
        response = client.post("/query/stream", json={"question": "What is the travel policy?"}, headers=headers)
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]
        
        lines = [line for line in response.iter_lines() if line]
        assert len(lines) > 0
        
        import json
        events = []
        for line in lines:
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                
        assert any(e["type"] == "metadata" for e in events)
        assert any(e["type"] == "token" and e.get("token") == "mocked " for e in events)
        assert any(e["type"] == "done" for e in events)
