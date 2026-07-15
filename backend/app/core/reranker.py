from typing import Any, Dict, List, Optional

from app.config import get_settings


class BgeReranker:
    """Reranks retrieved text chunks using a cross-encoder model for high precision."""
    def __init__(self, model_name: Optional[str] = None) -> None:
        settings = get_settings()
        self.model_name = model_name or settings.rerank_model_name
        self._model: Optional[Any] = None

    @property
    def model(self) -> Any:
        """Lazy load the CrossEncoder model to avoid unnecessary memory overhead on imports."""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name)
        assert self._model is not None
        return self._model

    def rerank(self, query: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Compute relevance scores for a query and a set of chunks, and sort by relevance.
        
        Args:
            query: The user question or search query.
            chunks: A list of dict chunks containing at least a "text" key.
            
        Returns:
            List[Dict[str, Any]]: Reranked chunks sorted by relevance score descending.
        """
        if not chunks:
            return []

        # Construct query-chunk text pairs for cross-encoder inference
        pairs = [[query, chunk["text"]] for chunk in chunks]
        scores = self.model.predict(pairs)  # type: ignore[arg-type]

        # Attach scores and return sorted list
        for chunk, score in zip(chunks, scores):
            chunk["rerank_score"] = float(score)

        return sorted(chunks, key=lambda x: x["rerank_score"], reverse=True)
