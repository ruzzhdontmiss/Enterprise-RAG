import logging
import uuid
import json
import queue
import threading
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import get_current_tenant_id, get_current_user
from app.core.database import get_db
from app.core.rag_graph import GraphState, app_graph
from app.models.chat_message import ChatMessage
from app.models.document import Document
from app.models.query_trace import QueryTrace
from app.models.user import User

logger = logging.getLogger("app.api.query")
router = APIRouter(prefix="/query", tags=["query"])


class QueryRequest(BaseModel):
    question: str


class Citation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    filename: str
    page_or_section: str
    chunk_text_snippet: str


class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    retrieved_chunk_count: int


@router.post("", response_model=QueryResponse)
def run_query(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Query the knowledge base using the adaptive retrieval LangGraph flow, resolve citations, and persist log event."""
    initial_state: GraphState = {
        "question": payload.question,
        "search_query": "",
        "raw_chunks": [],
        "reranked_chunks": [],
        "answer": "",
        "citations": [],
        "retrieved_chunk_count": 0,
        "rerun_count": 0,
        "tenant_id": tenant_id,
        "user_id": current_user.id,
        "trace": {},
    }

    # Run the adaptive RAG state graph
    final_state = app_graph.invoke(initial_state)

    # Log execution traces for observability (Phase 6 hook)
    logger.info("Adaptive RAG Trace for tenant %s: %s", tenant_id, final_state["trace"])

    # Resolve document filenames from the relational database for final citations formatting
    resolved_citations = []
    citations_list = final_state.get("citations", [])
    
    if citations_list:
        doc_ids = list({uuid.UUID(str(c["document_id"])) for c in citations_list if c.get("document_id")})
        documents_map = {}
        if doc_ids:
            docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
            documents_map = {d.id: d for d in docs}

        for c in citations_list:
            doc_uuid = uuid.UUID(str(c["document_id"]))
            doc = documents_map.get(doc_uuid)
            filename = doc.filename if doc else "unknown"

            resolved_citations.append(
                Citation(
                    document_id=doc_uuid,
                    filename=filename,
                    page_or_section=c["page_or_section"],
                    chunk_text_snippet=c["chunk_text_snippet"],
                )
            )

    # Persist log event details to database
    citations_data = [
        {
            "document_id": str(rc.document_id),
            "filename": rc.filename,
            "page_or_section": rc.page_or_section,
            "chunk_text_snippet": rc.chunk_text_snippet,
        }
        for rc in resolved_citations
    ]
    
    db_msg = ChatMessage(
        tenant_id=tenant_id,
        user_id=current_user.id,
        question=payload.question,
        answer=final_state["answer"],
        citations_json=citations_data,
    )
    db.add(db_msg)

    # Extract rewritten query safely, converting mocks to strings
    raw_rewrite = final_state["trace"].get("query_rewrite", {}).get("rewritten_query")
    rewritten_str = str(raw_rewrite) if raw_rewrite is not None else None

    # Persist QueryTrace for telemetry & diagnostic observability
    db_trace = QueryTrace(
        tenant_id=tenant_id,
        question=payload.question,
        rewritten_query=rewritten_str,
        retrieved_chunk_ids=[str(c["document_id"]) for c in final_state.get("reranked_chunks", []) if "document_id" in c],
        hybrid_scores={str(c["document_id"]) + "_" + str(c.get("chunk_index") or 0): float(c.get("rrf_score") or 0.0) for c in final_state.get("raw_chunks", []) if "document_id" in c},
        rerank_scores={str(c["document_id"]) + "_" + str(c.get("chunk_index") or 0): float(c.get("rerank_score") or 0.0) for c in final_state.get("reranked_chunks", []) if "document_id" in c},
        reretrieval_triggered=final_state.get("rerun_count", 0) > 0,
        final_answer=final_state["answer"],
        latency_ms_per_node=final_state["trace"].get("latency_ms", {}),
    )
    db.add(db_trace)
    
    db.commit()

    return QueryResponse(
        answer=final_state["answer"],
        citations=resolved_citations,
        retrieved_chunk_count=final_state["retrieved_chunk_count"],
    )


@router.post("/stream")
def run_query_stream(
    payload: QueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Query the knowledge base and return answers streamed using Server-Sent Events (SSE)."""
    event_queue: queue.Queue = queue.Queue()

    def callback(event: dict):
        event_queue.put(event)

    initial_state: GraphState = {
        "question": payload.question,
        "search_query": "",
        "raw_chunks": [],
        "reranked_chunks": [],
        "answer": "",
        "citations": [],
        "retrieved_chunk_count": 0,
        "rerun_count": 0,
        "tenant_id": tenant_id,
        "user_id": current_user.id,
        "trace": {},
        "stream_callback": callback,
    }

    def run_graph():
        try:
            final_state = app_graph.invoke(initial_state)
            event_queue.put({"type": "graph_done", "final_state": final_state})
        except Exception as e:
            logger.error("Error in query stream thread: %s", e)
            event_queue.put({"type": "error", "error": str(e)})
            event_queue.put({"type": "done"})

    threading.Thread(target=run_graph).start()

    def event_generator():
        final_state = None
        while True:
            try:
                event = event_queue.get(timeout=30)
                if event.get("type") == "graph_done":
                    final_state = event["final_state"]
                    continue
                
                if event.get("type") == "done":
                    if final_state:
                        # Resolve citations in main thread
                        resolved_citations = []
                        citations_list = final_state.get("citations", [])
                        if citations_list:
                            doc_ids = list({uuid.UUID(str(c["document_id"])) for c in citations_list if c.get("document_id")})
                            documents_map = {}
                            if doc_ids:
                                docs = db.query(Document).filter(Document.id.in_(doc_ids)).all()
                                documents_map = {d.id: d for d in docs}

                            for c in citations_list:
                                doc_uuid = uuid.UUID(str(c["document_id"]))
                                doc = documents_map.get(doc_uuid)
                                filename = doc.filename if doc else "unknown"
                                resolved_citations.append({
                                    "document_id": str(doc_uuid),
                                    "filename": filename,
                                    "page_or_section": c["page_or_section"],
                                    "chunk_text_snippet": c["chunk_text_snippet"],
                                })

                        try:
                            # Save ChatMessage
                            db_msg = ChatMessage(
                                tenant_id=tenant_id,
                                user_id=current_user.id,
                                question=payload.question,
                                answer=final_state["answer"],
                                citations_json=resolved_citations,
                            )
                            db.add(db_msg)

                            # Save QueryTrace
                            raw_rewrite = final_state["trace"].get("query_rewrite", {}).get("rewritten_query")
                            rewritten_str = str(raw_rewrite) if raw_rewrite is not None else None

                            db_trace = QueryTrace(
                                tenant_id=tenant_id,
                                question=payload.question,
                                rewritten_query=rewritten_str,
                                retrieved_chunk_ids=[str(c["document_id"]) for c in final_state.get("reranked_chunks", []) if "document_id" in c],
                                hybrid_scores={str(c["document_id"]) + "_" + str(c.get("chunk_index") or 0): float(c.get("rrf_score") or 0.0) for c in final_state.get("raw_chunks", []) if "document_id" in c},
                                rerank_scores={str(c["document_id"]) + "_" + str(c.get("chunk_index") or 0): float(c.get("rerank_score") or 0.0) for c in final_state.get("reranked_chunks", []) if "document_id" in c},
                                reretrieval_triggered=final_state.get("rerun_count", 0) > 0,
                                final_answer=final_state["answer"],
                                latency_ms_per_node=final_state["trace"].get("latency_ms", {}),
                            )
                            db.add(db_trace)
                            db.commit()
                        except Exception as db_err:
                            logger.error("DB error in query stream commit: %s", db_err)
                            db.rollback()
                    
                    yield f"data: {json.dumps(event)}\n\n"
                    break
                
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break

    return StreamingResponse(event_generator(), media_type="text/event-stream")
