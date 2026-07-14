import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_tenant_id, require_role
from app.core.database import get_db
from app.models.query_trace import QueryTrace

router = APIRouter(prefix="/admin", tags=["admin"])


class QueryTraceSummary(BaseModel):
    id: uuid.UUID
    question: str
    rewritten_query: Optional[str] = None
    reretrieval_triggered: bool
    final_answer: str
    created_at: datetime
    total_latency_ms: float


class QueryTraceDetail(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    question: str
    rewritten_query: Optional[str] = None
    retrieved_chunk_ids: List[str]
    hybrid_scores: Dict[str, float]
    rerank_scores: Dict[str, float]
    reretrieval_triggered: bool
    final_answer: str
    latency_ms_per_node: Dict[str, float]
    created_at: datetime


@router.get("/traces", response_model=List[QueryTraceSummary])
def get_traces(
    limit: int = 10,
    offset: int = 0,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    _admin: None = Depends(require_role("admin")),
):
    """Retrieve a paginated, tenant-scoped list of query execution traces for admin diagnosis."""
    traces = (
        db.query(QueryTrace)
        .filter(QueryTrace.tenant_id == tenant_id)
        .order_by(QueryTrace.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    summaries = []
    for t in traces:
        # Sum node latencies to calculate total latency
        total_latency = sum(t.latency_ms_per_node.values()) if t.latency_ms_per_node else 0.0
        
        summaries.append(
            QueryTraceSummary(
                id=t.id,
                question=t.question,
                rewritten_query=t.rewritten_query,
                reretrieval_triggered=t.reretrieval_triggered,
                final_answer=t.final_answer,
                created_at=t.created_at,
                total_latency_ms=total_latency,
            )
        )
    return summaries


@router.get("/traces/{trace_id}", response_model=QueryTraceDetail)
def get_trace_detail(
    trace_id: uuid.UUID,
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    _admin: None = Depends(require_role("admin")),
):
    """Retrieve full details of a specific execution trace, strictly scoped by tenant."""
    trace = (
        db.query(QueryTrace)
        .filter(QueryTrace.id == trace_id, QueryTrace.tenant_id == tenant_id)
        .first()
    )
    if not trace:
        raise HTTPException(status_code=404, detail="Query trace not found.")

    return QueryTraceDetail(
        id=trace.id,
        tenant_id=trace.tenant_id,
        question=trace.question,
        rewritten_query=trace.rewritten_query,
        retrieved_chunk_ids=trace.retrieved_chunk_ids,
        hybrid_scores=trace.hybrid_scores,
        rerank_scores=trace.rerank_scores,
        reretrieval_triggered=trace.reretrieval_triggered,
        final_answer=trace.final_answer,
        latency_ms_per_node=trace.latency_ms_per_node,
        created_at=trace.created_at,
    )
