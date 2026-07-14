import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QueryTrace(Base):
    """SQLAlchemy model representing the query-level observability execution trace.
    
    Contains details to debug generated answers (rewrites, ranks, latencies). Scoped strictly by tenant.
    """
    __tablename__ = "query_traces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    question: Mapped[str] = mapped_column(nullable=False)
    rewritten_query: Mapped[Optional[str]] = mapped_column(nullable=True)
    retrieved_chunk_ids: Mapped[Any] = mapped_column(JSON, nullable=False)
    hybrid_scores: Mapped[Any] = mapped_column(JSON, nullable=False)
    rerank_scores: Mapped[Any] = mapped_column(JSON, nullable=False)
    reretrieval_triggered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    final_answer: Mapped[str] = mapped_column(nullable=False)
    latency_ms_per_node: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<QueryTrace(id={self.id}, tenant={self.tenant_id}, q='{self.question[:20]}')>"
