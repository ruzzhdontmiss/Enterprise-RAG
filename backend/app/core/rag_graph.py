import time
import uuid
from functools import wraps
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, StateGraph

from app.config import get_settings
from app.core.llm_provider import MistralEmbeddingProvider, MistralLlmProvider
from app.core.reranker import BgeReranker
from app.core.vector_store import QdrantVectorStore


class GraphState(TypedDict, total=False):
    """Represents the execution state of the Adaptive Retrieval RAG graph."""
    question: str
    search_query: str
    raw_chunks: List[Dict[str, Any]]
    reranked_chunks: List[Dict[str, Any]]
    answer: str
    citations: List[Dict[str, Any]]
    retrieved_chunk_count: int
    rerun_count: int
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    trace: Dict[str, Any]
    stream_callback: Any


def time_node(func):
    """Decorator to measure and log node latency in GraphState trace."""
    @wraps(func)
    def wrapper(state: GraphState, *args, **kwargs) -> GraphState:
        if "trace" not in state or state["trace"] is None:
            state["trace"] = {}
        if "latency_ms" not in state["trace"]:
            state["trace"]["latency_ms"] = {}
            
        start_time = time.perf_counter()
        result = func(state, *args, **kwargs)
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        node_name = func.__name__.replace("_node", "")
        existing = state["trace"]["latency_ms"].get(node_name, 0.0)
        state["trace"]["latency_ms"][node_name] = existing + duration_ms
        return result
    return wrapper


@time_node
def rewrite_query_node(state: GraphState) -> GraphState:
    """LLM node that rewrites raw user question into optimized search keywords."""
    question = state["question"]
    words = question.split()
    
    # Heuristic: Skip rewriting for precise/short queries
    helper_words = {"how", "why", "what", "where", "who", "should", "can", "is", "are"}
    is_short = len(words) <= 3
    is_keyword_only = len(words) <= 5 and not any(w.lower() in helper_words for w in words)
    
    if is_short or is_keyword_only:
        state["search_query"] = question
        state["trace"]["query_rewrite"] = {
            "raw_question": question,
            "rewritten_query": question,
            "skipped": True,
        }
        return state

    # Call LLM to rewrite query
    system_prompt = (
        "You are a query rewriter for a Retrieval-Augmented Generation system.\n"
        "Rewrite the user's question into a concise, optimized search query (keywords and core terms) "
        "that is perfect for vector database search.\n"
        "Output ONLY the rewritten query, nothing else."
    )
    user_prompt = f"Question: {question}"
    
    generator = MistralLlmProvider()
    rewritten = generator.generate_answer(system_prompt, user_prompt).strip()
    
    state["search_query"] = rewritten
    state["trace"]["query_rewrite"] = {
        "raw_question": question,
        "rewritten_query": rewritten,
        "skipped": False,
    }
    return state


@time_node
def hybrid_search_node(state: GraphState) -> GraphState:
    """Retrieves document chunks using dense vector search and BM25 keywords, merging with RRF."""
    tenant_id = state["tenant_id"]
    query = state["search_query"]
    
    # Increase k limits during broadened search
    is_rerun = state.get("rerun_count", 0) > 0
    k = 10 if is_rerun else 5

    # 1. Dense vector search
    vector_store = QdrantVectorStore()
    embedder = MistralEmbeddingProvider()
    query_vector = embedder.embed_documents([query])[0]
    dense_results = vector_store.search_similar(
        tenant_id=tenant_id,
        query_vector=query_vector,
        limit=k,
    )

    # 2. Local BM25 keyword search over tenant corpus
    # Retrieve all points matching the tenant_id using the scroll API
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    scroll_filter = Filter(
        must=[
            FieldCondition(
                key="tenant_id",
                match=MatchValue(value=str(tenant_id)),
            )
        ]
    )
    
    scroll_response = vector_store.client.scroll(
        collection_name=vector_store.collection_name,
        scroll_filter=scroll_filter,
        limit=1000,
        with_payload=True,
    )
    points = scroll_response[0]

    top_bm25: List[Dict[str, Any]] = []
    
    if points:
        from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]
        
        corpus_chunks = []
        for p in points:
            if p.payload and "text" in p.payload:
                corpus_chunks.append(p.payload)
                
        if corpus_chunks:
            # Tokenize corpus for BM25
            tokenized_corpus = [c["text"].lower().split() for c in corpus_chunks]
            bm25 = BM25Okapi(tokenized_corpus)
            
            # Compute scores
            tokenized_query = query.lower().split()
            scores = bm25.get_scores(tokenized_query)
            
            bm25_results = []
            for chunk, score in zip(corpus_chunks, scores):
                bm25_results.append({
                    "document_id": chunk.get("document_id"),
                    "text": chunk.get("text"),
                    "page_number": chunk.get("page_number"),
                    "section": chunk.get("section"),
                    "chunk_index": chunk.get("chunk_index"),
                    "bm25_score": float(score),
                })
                
            bm25_results.sort(key=lambda x: float(x["bm25_score"] or 0.0), reverse=True)
            top_bm25 = bm25_results[:k]

    # 3. Reciprocal Rank Fusion (RRF) Merge
    # rank_bm25 is run locally on-the-fly.
    # Tradeoff: In-memory rank_bm25 is simple, self-contained, and works out-of-the-box
    # in any environment without special collection schemas, but loading all tenant chunks
    # into memory does not scale for millions of chunks. Using Qdrant sparse vectors scales
    # horizontally but requires deploying a separate tokenizer/embedding service.
    rrf_constant = 60
    rrf_scores: Dict[str, float] = {}
    chunk_map: Dict[str, Dict[str, Any]] = {}

    for rank, r in enumerate(dense_results):
        key = r["text"]
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (rrf_constant + rank + 1)
        chunk_map[key] = r

    for rank, r in enumerate(top_bm25):
        key = r["text"]
        rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (rrf_constant + rank + 1)
        if key not in chunk_map:
            chunk_map[key] = {
                "document_id": r["document_id"],
                "text": r["text"],
                "page_number": r["page_number"],
                "section": r["section"],
                "chunk_index": r.get("chunk_index"),
                "score": 0.0,
            }

    merged = []
    for key, score in rrf_scores.items():
        item = dict(chunk_map[key])
        item["rrf_score"] = score
        merged.append(item)

    merged.sort(key=lambda x: float(x["rrf_score"]), reverse=True)
    
    state["raw_chunks"] = merged
    state["trace"]["hybrid_search"] = {
        "query": query,
        "limit_k": k,
        "dense_count": len(dense_results),
        "bm25_count": len(top_bm25),
        "merged_count": len(merged),
    }
    return state


@time_node
def rerank_node(state: GraphState) -> GraphState:
    """Reranks hybrid search results using BgeReranker cross-encoder."""
    reranker = BgeReranker()
    reranked = reranker.rerank(state["search_query"], state["raw_chunks"])
    
    # Cap to top 5 reranked results
    state["reranked_chunks"] = reranked[:5]
    
    top_scores = [c.get("rerank_score", 0.0) for c in state["reranked_chunks"]]
    state["trace"]["rerank"] = {
        "top_scores": top_scores,
        "final_count": len(state["reranked_chunks"]),
    }
    return state


@time_node
def broaden_search_node(state: GraphState) -> GraphState:
    """Drops the rewritten query, increases limits, and resets search parameters."""
    state["rerun_count"] += 1
    state["search_query"] = state["question"]
    state["trace"]["broaden_search"] = {
        "rerun_count": state["rerun_count"],
        "original_question": state["question"],
    }
    return state


def route_after_rerank(state: GraphState) -> str:
    """Conditional router that implements the confidence gate check."""
    reranked = state.get("reranked_chunks", [])
    top_score = reranked[0].get("rerank_score", -99.0) if reranked else -99.0
    
    settings = get_settings()
    threshold = settings.rerank_confidence_threshold

    if top_score < threshold and state.get("rerun_count", 0) == 0:
        return "broaden_search"
    else:
        return "generate"


@time_node
def generate_node(state: GraphState) -> GraphState:
    """Grounded LLM response completions node."""
    settings = get_settings()
    reranked = state["reranked_chunks"]
    top_score = reranked[0].get("rerank_score", -99.0) if reranked else -99.0
    
    # Enforce score/gating floor (prevent hallucinations)
    if not reranked or top_score < settings.rerank_confidence_threshold:
        ans = "not enough information in the knowledge base"
        state["answer"] = ans
        state["citations"] = []
        state["retrieved_chunk_count"] = 0
        state["trace"]["generate"] = {"skipped": True, "reason": "Similarity gating below floor"}
        
        stream_cb = state.get("stream_callback")
        if stream_cb:
            stream_cb({
                "type": "metadata",
                "citations": [],
                "retrieved_chunk_count": 0,
            })
            for word in ans.split(" "):
                stream_cb({
                    "type": "token",
                    "token": word + " ",
                })
            stream_cb({
                "type": "done",
            })
        return state

    # Resolve document filenames for formatting citations
    # Using local mock resolution or DB lookup
    citations = []
    context_blocks = []
    
    # We can resolve filenames at API runtime or dynamically in node
    # Since DB Session is not in GraphState, we resolve citations structure here
    # and map filenames in the query route layer
    for idx, r in enumerate(reranked):
        page_or_section = r.get("section") or f"Page {r.get('page_number')}"
        citations.append({
            "document_id": r["document_id"],
            "filename": r.get("filename", "unknown"),
            "page_or_section": page_or_section,
            "chunk_text_snippet": r["text"],
        })
        context_blocks.append(
            f"[{idx + 1}] Location: {page_or_section}\n"
            f"Content: {r['text']}\n"
        )

    context_text = "\n".join(context_blocks)
    
    system_prompt = (
        "You are a helpful assistant for EnterpriseRAG. Answer the user's question ONLY using the provided documents context.\n"
        "For each claim or statement you make, you must cite which source location you retrieved the information from using "
        "matching bracket references (e.g. [1], [2]).\n"
        "If the context does not contain the answer, reply with 'not enough information in the knowledge base'.\n"
        "Do not make up facts or use external knowledge."
    )
    user_prompt = f"Question: {state['question']}\n\nContext Chunks:\n{context_text}"

    generator = MistralLlmProvider()
    
    stream_cb = state.get("stream_callback")
    if stream_cb:
        stream_cb({
            "type": "metadata",
            "citations": citations,
            "retrieved_chunk_count": len(reranked),
        })
        
        answer_tokens = []
        for token in generator.generate_answer_stream(system_prompt, user_prompt):
            answer_tokens.append(token)
            stream_cb({
                "type": "token",
                "token": token,
            })
            
        answer = "".join(answer_tokens)
        stream_cb({
            "type": "done",
        })
    else:
        answer = generator.generate_answer(system_prompt, user_prompt)
    
    state["answer"] = answer
    state["citations"] = citations
    state["retrieved_chunk_count"] = len(reranked)
    state["trace"]["generate"] = {"skipped": False, "chunk_count": len(reranked)}
    return state


# Build LangGraph workflow
workflow = StateGraph(GraphState)

workflow.add_node("rewrite_query", rewrite_query_node)
workflow.add_node("hybrid_search", hybrid_search_node)
workflow.add_node("rerank", rerank_node)
workflow.add_node("broaden_search", broaden_search_node)
workflow.add_node("generate", generate_node)

workflow.set_entry_point("rewrite_query")

workflow.add_edge("rewrite_query", "hybrid_search")
workflow.add_edge("hybrid_search", "rerank")

workflow.add_conditional_edges(
    "rerank",
    route_after_rerank,
    {
        "broaden_search": "broaden_search",
        "generate": "generate",
    },
)

workflow.add_edge("broaden_search", "hybrid_search")
workflow.add_edge("generate", END)

app_graph = workflow.compile()
