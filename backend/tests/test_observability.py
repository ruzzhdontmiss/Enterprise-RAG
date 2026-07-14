import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.models.query_trace import QueryTrace
from app.core.auth import create_access_token

client = TestClient(app)


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_trace_written_on_every_query(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that a QueryTrace row is successfully written to database for every /query call."""
    tenant = Tenant(id=uuid.uuid4(), name="Obs Org")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="obs_user@obs.com",
        hashed_password="pwd",
        role="admin",
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
    mock_generate.return_value = "Grounded response"

    response = client.post("/query", json={"question": "What is security policy?"}, headers=headers)
    assert response.status_code == 200

    # Assert trace exists in DB
    traces = db_session.query(QueryTrace).all()
    assert len(traces) == 1
    trace = traces[0]
    assert trace.tenant_id == tenant.id
    assert trace.question == "What is security policy?"
    assert trace.reretrieval_triggered is False
    assert "rewrite_query" in trace.latency_ms_per_node


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_trace_is_tenant_scoped_and_admin_only(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that trace viewing is strictly limited to the tenant's admin users."""
    tenant_a = Tenant(id=uuid.uuid4(), name="Tenant A")
    tenant_b = Tenant(id=uuid.uuid4(), name="Tenant B")
    db_session.add_all([tenant_a, tenant_b])
    db_session.commit()
    
    admin_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="admin_a@tenant.com",
        hashed_password="pwd",
        role="admin",
    )
    member_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="member_a@tenant.com",
        hashed_password="pwd",
        role="member",
    )
    admin_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email="admin_b@tenant.com",
        hashed_password="pwd",
        role="admin",
    )
    db_session.add_all([admin_a, member_a, admin_b])
    db_session.commit()

    mock_embed.return_value = [[0.1] * 1024]
    mock_search.return_value = []
    mock_scroll.return_value = ([], None)
    mock_rerank.side_effect = lambda q, chunks: chunks
    mock_generate.return_value = "Response"

    # Create a trace under Tenant B
    trace_b = QueryTrace(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        question="Question B",
        rewritten_query="Question B",
        retrieved_chunk_ids=[],
        hybrid_scores={},
        rerank_scores={},
        reretrieval_triggered=False,
        final_answer="Answer B",
        latency_ms_per_node={},
    )
    db_session.add(trace_b)
    db_session.commit()

    # Create a trace under Tenant A
    trace_a = QueryTrace(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        question="Question A",
        rewritten_query="Question A",
        retrieved_chunk_ids=[],
        hybrid_scores={},
        rerank_scores={},
        reretrieval_triggered=False,
        final_answer="Answer A",
        latency_ms_per_node={},
    )
    db_session.add(trace_a)
    db_session.commit()

    # Tokens
    token_admin_a = create_access_token(user_id=admin_a.id, tenant_id=tenant_a.id, role=admin_a.role)
    token_member_a = create_access_token(user_id=member_a.id, tenant_id=tenant_a.id, role=member_a.role)
    token_admin_b = create_access_token(user_id=admin_b.id, tenant_id=tenant_b.id, role=admin_b.role)

    # 1. Member A tries to get list (should be 403 Forbidden)
    res = client.get("/admin/traces", headers={"Authorization": f"Bearer {token_member_a}"})
    assert res.status_code == 403
    
    # 2. Member A tries to get trace detail A (should be 403 Forbidden)
    res = client.get(f"/admin/traces/{trace_a.id}", headers={"Authorization": f"Bearer {token_member_a}"})
    assert res.status_code == 403

    # 3. Admin A retrieves traces list (should be 200 OK and ONLY show trace A)
    res = client.get("/admin/traces", headers={"Authorization": f"Bearer {token_admin_a}"})
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["question"] == "Question A"

    # 4. Admin A retrieves trace B detail (cross-tenant lookup - should return 404/403)
    res = client.get(f"/admin/traces/{trace_b.id}", headers={"Authorization": f"Bearer {token_admin_a}"})
    assert res.status_code in [403, 404]

    # 5. Admin B retrieves trace B detail (should return 200 OK)
    res = client.get(f"/admin/traces/{trace_b.id}", headers={"Authorization": f"Bearer {token_admin_b}"})
    assert res.status_code == 200
    assert res.json()["question"] == "Question B"


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_trace_includes_reretrieval_flag_when_triggered(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that query trace marks reretrieval_triggered as True when re-retrieval occurs."""
    tenant = Tenant(id=uuid.uuid4(), name="Gate Org")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="gate@org.com",
        hashed_password="pwd",
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    mock_embed.return_value = [[0.1] * 1024]
    mock_scroll.return_value = ([], None)
    mock_generate.return_value = "not enough information in the knowledge base"
    
    # First search: returns a chunk but rerank scores it 0.1 (low confidence) -> triggers broaden search
    # Second search: returns a chunk scored 0.95 (high confidence)
    mock_search.return_value = [{"document_id": str(uuid.uuid4()), "text": "Low confidence chunk", "page_number": 1, "section": "Sec", "score": 0.5}]
    
    # We simulate rerank scores: first call yields 0.1, second call yields 0.95
    mock_rerank.side_effect = [
        [{"document_id": str(uuid.uuid4()), "text": "Low confidence chunk", "page_number": 1, "section": "Sec", "rerank_score": 0.1}],
        [{"document_id": str(uuid.uuid4()), "text": "High confidence chunk", "page_number": 1, "section": "Sec", "rerank_score": 0.95}]
    ]

    response = client.post("/query", json={"question": "What is life?"}, headers=headers)
    assert response.status_code == 200

    traces = db_session.query(QueryTrace).all()
    assert len(traces) == 1
    assert traces[0].reretrieval_triggered is True


@patch("app.core.reranker.BgeReranker.rerank")
@patch("qdrant_client.QdrantClient.scroll")
@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
def test_trace_latency_breakdown_per_node_recorded(
    mock_search: MagicMock,
    mock_embed: MagicMock,
    mock_generate: MagicMock,
    mock_scroll: MagicMock,
    mock_rerank: MagicMock,
    db_session: Session,
) -> None:
    """Test that QueryTrace logs distinct, non-negative millisecond latencies for each graph node."""
    tenant = Tenant(id=uuid.uuid4(), name="Latency Org")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="lat@org.com",
        hashed_password="pwd",
        role="admin",
    )
    db_session.add(user)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}

    mock_embed.return_value = [[0.1] * 1024]
    mock_search.return_value = []
    mock_scroll.return_value = ([], None)
    mock_rerank.side_effect = lambda q, chunks: chunks
    mock_generate.return_value = "Response"

    client.post("/query", json={"question": "hello?"}, headers=headers)

    trace = db_session.query(QueryTrace).first()
    assert trace is not None
    
    latencies = trace.latency_ms_per_node
    assert "rewrite_query" in latencies
    assert "hybrid_search" in latencies
    assert "rerank" in latencies
    assert "generate" in latencies
    
    for val in latencies.values():
        assert float(val) >= 0.0
