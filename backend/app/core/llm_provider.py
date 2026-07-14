import hashlib
import random
import threading
import time
from typing import Iterator, List, Optional

from mistralai.client import Mistral

from app.config import get_settings


class BaseEmbeddingProvider:
    """Interface for embedding generation providers."""
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate vector embeddings for a batch of strings.
        
        Args:
            texts: List of strings to embed.
            
        Returns:
            List[List[float]]: Matrix of float vectors.
        """
        raise NotImplementedError()


class MistralEmbeddingProvider(BaseEmbeddingProvider):
    """Mistral API implementation of BaseEmbeddingProvider.
    
    Includes thread-safe cache to avoid redundant API hits and exponential backoff retry.
    """
    _cache: dict[str, List[float]] = {}
    _cache_lock = threading.Lock()

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.mistral_api_key
        self.model = model or settings.mistral_embed_model
        self.client = Mistral(api_key=self.api_key)

    def _embed_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Call the Mistral API to embed text with exponential backoff on retryable errors."""
        max_retries = 5
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    inputs=texts,
                )
                return [item.embedding for item in response.data]  # type: ignore[misc]
            except Exception as e:
                is_retryable = "429" in str(e) or "50" in str(e) or attempt < 2
                if is_retryable and attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                else:
                    raise e
        raise RuntimeError("Failed to generate embeddings after max retries")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings with lookup cache and batching of misses."""
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        misses = []
        miss_indices = []

        # Thread-safe read check
        with self._cache_lock:
            for idx, text in enumerate(texts):
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if text_hash in self._cache:
                    results[idx] = self._cache[text_hash]
                else:
                    misses.append(text)
                    miss_indices.append(idx)

        # Retrieve misses from API
        if misses:
            embeddings = self._embed_with_retry(misses)
            
            # Thread-safe write cache
            with self._cache_lock:
                for idx, embedding in zip(miss_indices, embeddings):
                    text_hash = hashlib.sha256(texts[idx].encode("utf-8")).hexdigest()
                    self._cache[text_hash] = embedding
                    results[idx] = embedding

        return results  # type: ignore[return-value]


class BaseLlmProvider:
    """Interface for text generation."""
    def generate_answer(self, system_prompt: str, user_prompt: str) -> str:
        """Generate text answer based on context and question."""
        raise NotImplementedError()

    def generate_answer_stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Stream response text tokens based on context and question."""
        raise NotImplementedError()


class MistralLlmProvider(BaseLlmProvider):
    """Mistral API implementation of BaseLlmProvider for generation completions."""
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.mistral_api_key
        self.model = model or settings.mistral_generation_model
        self.client = Mistral(api_key=self.api_key)

    def generate_answer(self, system_prompt: str, user_prompt: str) -> str:
        """Call Mistral chat completions to generate response text."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        
        response = self.client.chat.complete(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
        )
        choice = response.choices[0]
        if choice.message and choice.message.content:
            content = choice.message.content
            if isinstance(content, str):
                return content
        return ""

    def generate_answer_stream(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        """Stream response tokens using Mistral Client, falling back to simulated delay when offline."""
        if self.api_key == "your_mistral_api_key_here" or not self.api_key:
            # Fallback/Simulation mode: yield words of mock answer
            full_ans = self.generate_answer(system_prompt, user_prompt)
            for word in full_ans.split(" "):
                yield word + " "
                time.sleep(0.03)
            return

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        try:
            response = self.client.chat.stream(
                model=self.model,
                messages=messages,  # type: ignore[arg-type]
            )
            for chunk in response:
                if chunk.data.choices[0].delta.content:
                    yield chunk.data.choices[0].delta.content
        except Exception:
            # Fallback to sync chunk yield on error
            full_ans = self.generate_answer(system_prompt, user_prompt)
            for word in full_ans.split(" "):
                yield word + " "
                time.sleep(0.03)
