from typing import List, Optional
from app.core.parser import DocumentPage


class DocumentChunk:
    """Represents a single granular text chunk extracted from a document page.
    
    Carries metadata identifying its source document location (page, section).
    """
    def __init__(self, text: str, page_number: int, section: str, chunk_index: int) -> None:
        self.text = text
        self.page_number = page_number
        self.section = section
        self.chunk_index = chunk_index

    def __repr__(self) -> str:
        return (
            f"<DocumentChunk(index={self.chunk_index}, page={self.page_number}, "
            f"section='{self.section}', text_len={len(self.text)})>"
        )


class BaseChunker:
    """Abstract Base Class defining the chunking interface."""
    def chunk(self, pages: List[DocumentPage]) -> List[DocumentChunk]:
        """Split pages into smaller chunks, preserving source metadata.
        
        Args:
            pages: List of DocumentPage objects.
            
        Returns:
            List[DocumentChunk]: Sequentially indexed document chunks.
        """
        raise NotImplementedError()


class RecursiveCharacterChunker(BaseChunker):
    """Recursively splits document text into chunks based on separator priority."""
    def __init__(
        self,
        chunk_size: int = 500,  # target size in tokens
        chunk_overlap: int = 50,  # target overlap in tokens
        separators: Optional[List[str]] = None,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators or ["\n\n", "\n", " ", ""]

    def _count_tokens(self, text: str) -> int:
        """Estimate token count based on standard English word count ratio (~1.3 tokens per word)."""
        words = text.split()
        return int(len(words) * 1.3)

    def _get_overlap_text(self, text: str) -> str:
        """Extract a string suffix from text representing the target overlap tokens."""
        words = text.split()
        # overlap count in words
        overlap_words_count = int(self.chunk_overlap / 1.3)
        if overlap_words_count <= 0:
            overlap_words_count = 1
        overlap_words = words[-overlap_words_count:] if len(words) > overlap_words_count else words
        return " ".join(overlap_words)

    def _split_text(self, text: str, separators: List[str]) -> List[str]:
        """Recursively split text using separators list."""
        if self._count_tokens(text) <= self.chunk_size:
            return [text]

        if not separators:
            # Fallback if all separators exhausted: split by word count
            words = text.split()
            chunks = []
            current_chunk: List[str] = []
            current_count = 0
            
            chunk_size_words = int(self.chunk_size / 1.3)
            overlap_words_count = int(self.chunk_overlap / 1.3)
            if chunk_size_words <= 0:
                chunk_size_words = 1
            
            for word in words:
                if current_count >= chunk_size_words:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = current_chunk[-overlap_words_count:] if len(current_chunk) > overlap_words_count else current_chunk
                    current_chunk.append(word)
                    current_count = len(current_chunk)
                else:
                    current_chunk.append(word)
                    current_count += 1
            if current_chunk:
                chunks.append(" ".join(current_chunk))
            return chunks

        separator = separators[0]
        splits = text.split(separator)
        splits = [s for s in splits if s.strip()]

        chunks = []
        current_doc = ""

        for split in splits:
            if self._count_tokens(split) > self.chunk_size:
                if current_doc:
                    chunks.append(current_doc)
                    current_doc = ""
                # Recursively split the long block with remaining separators
                recursed = self._split_text(split, separators[1:])
                chunks.extend(recursed)
            else:
                potential_doc = (current_doc + separator + split) if current_doc else split
                if self._count_tokens(potential_doc) > self.chunk_size:
                    if current_doc:
                        chunks.append(current_doc)
                    if self.chunk_overlap > 0 and current_doc:
                        overlap_text = self._get_overlap_text(current_doc)
                        current_doc = (overlap_text + separator + split) if overlap_text else split
                    else:
                        current_doc = split
                else:
                    current_doc = potential_doc

        if current_doc:
            chunks.append(current_doc)

        return chunks

    def chunk(self, pages: List[DocumentPage]) -> List[DocumentChunk]:
        """Split a list of parsed pages into chunks, preserving page and section metadata."""
        all_chunks = []
        chunk_index = 0
        for page in pages:
            page_text = page.text.strip()
            if not page_text:
                continue
            splits = self._split_text(page_text, self.separators)
            for split_text in splits:
                split_text = split_text.strip()
                if not split_text:
                    continue
                all_chunks.append(
                    DocumentChunk(
                        text=split_text,
                        page_number=page.page_number,
                        section=page.section,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1
        return all_chunks
