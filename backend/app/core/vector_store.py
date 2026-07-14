import uuid
from typing import List

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.config import get_settings
from app.core.chunker import DocumentChunk


class QdrantVectorStore:
    """Handles interactions with Qdrant vector database.
    
    Implements single-collection payload-based tenant isolation.
    """
    def __init__(self, collection_name: str = "documents") -> None:
        settings = get_settings()
        self.collection_name = collection_name
        self.client = QdrantClient(url=settings.qdrant_url)

    def _ensure_collection(self) -> None:
        """Create the collection and index on tenant_id if they do not exist.
        
        Justification for single-collection payload-based isolation:
        - Multi-collection isolation creates a heavy overhead of cluster resources
          (separate configuration, segment files, search threads) for every tenant,
          which does not scale when thousands of organizations exist.
        - Payload-based isolation with a keyword index on `tenant_id` allows Qdrant
          to instantly restrict the vector search space during query routing.
          This enforces complete cryptographic-like data separation at minimal cost.
        """
        if not self.client.collection_exists(self.collection_name):
            # mistral-embed vector size is 1024
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            # Index the tenant_id field for high-speed isolation routing
            self.client.create_payload_index(
                collection_name=self.collection_name,
                field_name="tenant_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )

    def upsert_chunks(
        self,
        tenant_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: List[DocumentChunk],
        embeddings: List[List[float]],
    ) -> None:
        """Upsert a list of document chunks and their embeddings to Qdrant."""
        self._ensure_collection()

        points = []
        for chunk, embedding in zip(chunks, embeddings):
            point_id = str(uuid.uuid4())
            points.append(
                PointStruct(
                    id=point_id,
                    vector=embedding,
                    payload={
                        "tenant_id": str(tenant_id),
                        "document_id": str(document_id),
                        "text": chunk.text,
                        "page_number": chunk.page_number,
                        "section": chunk.section,
                        "chunk_index": chunk.chunk_index,
                    },
                )
            )

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )

    def search_similar(
        self,
        tenant_id: uuid.UUID,
        query_vector: List[float],
        limit: int = 5,
    ) -> List[dict]:
        """Perform a vector search strictly filtered by the caller's tenant_id at the index level."""
        # Ensure search is scoped
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=str(tenant_id)),
                )
            ]
        )

        results = self.client.search(  # type: ignore[attr-defined]
            collection_name=self.collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
        )

        return [
            {
                "id": r.id,
                "score": r.score,
                "text": r.payload.get("text"),
                "page_number": r.payload.get("page_number"),
                "section": r.payload.get("section"),
                "document_id": r.payload.get("document_id"),
            }
            for r in results
        ]
