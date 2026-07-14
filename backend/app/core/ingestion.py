import io
import logging
import uuid
from sqlalchemy.orm import Session

from app.core.chunker import RecursiveCharacterChunker
from app.core.llm_provider import MistralEmbeddingProvider
from app.core.parser import BaseParser, DocxParser, PDFParser, TxtParser
from app.core.vector_store import QdrantVectorStore
from app.models.document import Document

logger = logging.getLogger(__name__)


def process_document_ingestion(
    document_id: uuid.UUID,
    file_content: bytes,
    filename: str,
    db_session: Session,
) -> None:
    """Ingest a document by parsing, chunking, embedding, and storing in Qdrant.
    
    Manages Document.status state machine (processing -> ready / failed) and commits
    to database. Rollbacks on errors and records the failure message.
    """
    doc = db_session.query(Document).filter_by(id=document_id).first()
    if not doc:
        logger.error(f"Document {document_id} not found in database.")
        return

    # Update status to processing
    doc.status = "processing"
    db_session.commit()

    try:
        # Determine parser by extension
        ext = filename.split(".")[-1].lower()
        parser: BaseParser
        if ext == "pdf":
            parser = PDFParser()
        elif ext == "docx":
            parser = DocxParser()
        elif ext == "txt":
            parser = TxtParser()
        else:
            raise ValueError(f"Unsupported file type extension: {ext}")

        # Parse text into page structures
        stream = io.BytesIO(file_content)
        pages = parser.parse(stream, filename)
        if not pages or all(not p.text.strip() for p in pages):
            raise ValueError("No extractable text content found in the document.")

        # Chunk parsed text
        chunker = RecursiveCharacterChunker()
        chunks = chunker.chunk(pages)
        if not chunks:
            raise ValueError("Document yielded zero text chunks after recursive splitting.")

        # Embed chunks utilizing cached and rate-limited provider
        embedder = MistralEmbeddingProvider()
        chunk_texts = [c.text for c in chunks]
        embeddings = embedder.embed_documents(chunk_texts)

        # Scoped Qdrant storage with tenant_id payload filtering
        vector_store = QdrantVectorStore()
        vector_store.upsert_chunks(
            tenant_id=doc.tenant_id,
            document_id=doc.id,
            chunks=chunks,
            embeddings=embeddings,
        )

        # Update status to ready
        doc.status = "ready"
        doc.error_message = None
        db_session.commit()
        logger.info(f"Ingestion succeeded for document {doc.id} ({filename})")

    except Exception as e:
        logger.exception(f"Ingestion failed for document {document_id}")
        db_session.rollback()
        # Mark document as failed and persist details
        doc.status = "failed"
        doc.error_message = str(e)
        db_session.commit()
