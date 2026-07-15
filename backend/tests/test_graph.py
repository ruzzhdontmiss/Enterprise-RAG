import uuid
from unittest.mock import MagicMock, patch

from app.core.rag_graph import GraphState

# We import the graph nodes directly for unit testing
from app.core.rag_graph import (
    rewrite_query_node,
    hybrid_search_node,
    rerank_node,
    broaden_search_node,
    route_after_rerank,
)


@patch("app.core.llm_provider.MistralLlmProvider.generate_answer")
def test_query_rewrite_skipped_for_precise_query(mock_generate: MagicMock) -> None:
    """Test that a short query bypasses the LLM rewrite node to save API calls."""
    state = GraphState(
        question="MFA policy doc",
        search_query="",
        raw_chunks=[],
        reranked_chunks=[],
        answer="",
        citations=[],
        retrieved_chunk_count=0,
        rerun_count=0,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace={}
    )
    
    new_state = rewrite_query_node(state)
    
    # Assert query rewrite is identical to original question and skip is logged
    assert new_state["search_query"] == "MFA policy doc"
    assert new_state["trace"]["query_rewrite"]["skipped"] is True
    assert not mock_generate.called


@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
@patch("qdrant_client.QdrantClient.scroll")
def test_hybrid_search_merges_dense_and_bm25_results(
    mock_scroll: MagicMock,
    mock_search: MagicMock,
    mock_embed: MagicMock,
) -> None:
    """Test that dense and BM25 results are correctly merged using Reciprocal Rank Fusion."""
    tenant_id = uuid.uuid4()
    doc_id = str(uuid.uuid4())
    
    # Mock embeddings
    mock_embed.return_value = [[0.1] * 1024]
    
    # Mock Qdrant dense vector search returning chunk A and B
    mock_search.return_value = [
        {"document_id": doc_id, "text": "Dental checkups are covered.", "page_number": 1, "section": "Dental", "score": 0.8},
        {"document_id": doc_id, "text": "Vision checks are covered.", "page_number": 1, "section": "Vision", "score": 0.7}
    ]
    
    # Mock scroll search returning all chunks for the tenant to build local BM25
    mock_scroll.return_value = (
        [
            MagicMock(payload={"document_id": doc_id, "text": "Dental checkups are covered.", "page_number": 1, "section": "Dental"}),
            MagicMock(payload={"document_id": doc_id, "text": "Vision checks are covered.", "page_number": 1, "section": "Vision"}),
            MagicMock(payload={"document_id": doc_id, "text": "Mental health counseling has a copay.", "page_number": 1, "section": "Mental"})
        ],
        None
    )
    
    state = GraphState(
        question="What does health cover for dental?",
        search_query="What does health cover for dental?",
        raw_chunks=[],
        reranked_chunks=[],
        answer="",
        citations=[],
        retrieved_chunk_count=0,
        rerun_count=0,
        tenant_id=tenant_id,
        user_id=uuid.uuid4(),
        trace={}
    )
    
    new_state = hybrid_search_node(state)
    
    # Verify RRF merges them and ranks 'Dental checkups are covered' as top
    # since it appears high in both keyword and dense searches
    chunks = new_state["raw_chunks"]
    assert len(chunks) > 0
    assert "Dental" in chunks[0]["text"]
    assert "rrf_score" in chunks[0]


@patch("sentence_transformers.CrossEncoder")
def test_rerank_orders_by_relevance(mock_cross_encoder_cls: MagicMock) -> None:
    """Test that the cross-encoder correctly computes and sorts chunks by rerank score."""
    mock_encoder = MagicMock()
    mock_cross_encoder_cls.return_value = mock_encoder
    
    # Mock predict returns score for each (query, chunk) pair
    # Let's say chunk B (index 1) gets a higher score than chunk A (index 0)
    mock_encoder.predict.return_value = [0.1, 0.95]
    
    state = GraphState(
        question="How many vacation days?",
        search_query="How many vacation days?",
        raw_chunks=[
            {"text": "Chunk A text", "page_number": 1},
            {"text": "Chunk B text", "page_number": 2}
        ],
        reranked_chunks=[],
        answer="",
        citations=[],
        retrieved_chunk_count=0,
        rerun_count=0,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace={}
    )
    
    new_state = rerank_node(state)
    
    # Assert sorting is correct (Chunk B is now first)
    reranked = new_state["reranked_chunks"]
    assert len(reranked) == 2
    assert reranked[0]["text"] == "Chunk B text"
    assert reranked[0]["rerank_score"] == 0.95


def test_confidence_gate_triggers_single_reretrieval_on_low_score() -> None:
    """Test that a low rerank score triggers query broadening exactly once."""
    # Low score (0.1) and rerun_count = 0 -> should route to broaden_search
    state = GraphState(
        question="Query",
        search_query="Query",
        raw_chunks=[],
        reranked_chunks=[{"text": "Low score text", "rerank_score": 0.1}],
        answer="",
        citations=[],
        retrieved_chunk_count=0,
        rerun_count=0,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace={}
    )
    
    route = route_after_rerank(state)
    assert route == "broaden_search"


def test_confidence_gate_does_not_loop_twice() -> None:
    """Test that the confidence gate routes to generation after one re-retrieval attempt."""
    # Low score (0.1) but rerun_count = 1 -> should route to generate (break loop)
    state = GraphState(
        question="Query",
        search_query="Query",
        raw_chunks=[],
        reranked_chunks=[{"text": "Low score text", "rerank_score": 0.1}],
        answer="",
        citations=[],
        retrieved_chunk_count=0,
        rerun_count=1,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace={}
    )
    
    route = route_after_rerank(state)
    assert route == "generate"


@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantVectorStore.search_similar")
@patch("qdrant_client.QdrantClient.scroll")
def test_broaden_search_node_resets_params(
    mock_scroll: MagicMock,
    mock_search: MagicMock,
    mock_embed: MagicMock,
) -> None:
    """Test that broaden_search drops rewrite, increases limit, and increments rerun_count."""
    state = GraphState(
        question="Original question",
        search_query="Rewritten query",
        raw_chunks=[],
        reranked_chunks=[],
        answer="",
        citations=[],
        retrieved_chunk_count=0,
        rerun_count=0,
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        trace={}
    )
    
    new_state = broaden_search_node(state)
    
    # Assert rerun count incremented and search query reset to original question
    assert new_state["rerun_count"] == 1
    assert new_state["search_query"] == "Original question"
