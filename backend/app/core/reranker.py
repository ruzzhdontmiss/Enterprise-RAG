from typing import Any, Dict, List, Optional

import cohere
from app.config import get_settings


class CohereReranker:
    """Reranks retrieved text chunks using Cohere's Rerank API for high precision."""
    def __init__(self, model_name: Optional[str] = None) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.rerank_model_name
        self._client: Optional[cohere.Client] = None

    @property
    def client(self) -> cohere.Client:
        """Lazy load the Cohere client to avoid initialization if not used."""
        if self._client is None:
            settings = get_settings()
            api_key = settings.cohere_api_key
            if not api_key:
                raise ValueError("cohere_api_key is not set in config.")
            self._client = cohere.Client(api_key=api_key)
        return self._client

    def rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compute relevance scores for a query and a set of chunks using Cohere, and sort by relevance.
        
        Args:
            query: The user question or search query.
            chunks: A list of dict chunks containing at least a "text" key.
            
        Returns:
            List[Dict[str, Any]]: Reranked chunks sorted by relevance score descending.
        """
        if not chunks:
            return []

        # Extract texts for Cohere API
        texts = [chunk["text"] for chunk in chunks]
        
        # Call Cohere Rerank v3 API
        response = self.client.rerank(
            query=query,
            documents=texts,
            model=self.model_name,
        )

        # Attach scores to the original chunks
        for result in response.results:
            chunks[result.index]["rerank_score"] = float(result.relevance_score)

        return sorted(chunks, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
