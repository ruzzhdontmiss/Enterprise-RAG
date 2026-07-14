import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from unittest.mock import MagicMock, patch

from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.models.document import Document
from app.core.auth import create_access_token
from app.core.parser import DocumentPage
from app.core.chunker import RecursiveCharacterChunker
from app.core.ingestion import process_document_ingestion

client = TestClient(app)


def test_chunking_preserves_source_metadata() -> None:
    """Test that RecursiveCharacterChunker splits text and retains page/section metadata."""
    chunker = RecursiveCharacterChunker()
    
    pages = [
        DocumentPage(text="This is a long text on page one. " * 50, page_number=1, section="Introduction"),
        DocumentPage(text="This is page two. " * 50, page_number=2, section="Methodology"),
    ]
    
    chunks = chunker.chunk(pages)
    
    # Assert we got some chunks
    assert len(chunks) > 1
    
    # Verify metadata is preserved and indices are sequential
    for idx, chunk in enumerate(chunks):
        assert chunk.chunk_index == idx
        assert chunk.page_number in [1, 2]
        if chunk.page_number == 1:
            assert chunk.section == "Introduction"
        else:
            assert chunk.section == "Methodology"
        assert len(chunk.text) > 0


def test_upload_rejects_unsupported_file_type(db_session: Session) -> None:
    """Test that uploading unsupported files returns 415."""
    # Seed tenant/user
    tenant = Tenant(id=uuid.uuid4(), name="Test Upload Tenant")
    db_session.add(tenant)
    db_session.commit()
    
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="uploader@test.com",
        hashed_password="hashed_password",
        role="member",
    )
    db_session.add(user)
    db_session.commit()
    
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    headers = {"Authorization": f"Bearer {token}"}
    
    files = {"file": ("unsupported.png", b"fake_png_data", "image/png")}
    response = client.post("/documents/upload", files=files, headers=headers)
    
    assert response.status_code == 415
    assert response.json()["detail"] == "Unsupported file type"


@patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents")
@patch("app.core.vector_store.QdrantClient")
def test_ingestion_writes_tenant_scoped_vectors(
    mock_qdrant_client_cls: MagicMock,
    mock_embed_documents: MagicMock,
    db_session: Session,
) -> None:
    """Test that document ingestion uploads vectors with tenant_id scoping payload."""
    mock_embed_documents.return_value = [[0.1] * 1024]
    
    # Instantiate mock QdrantClient methods
    mock_qdrant_client = MagicMock()
    mock_qdrant_client_cls.return_value = mock_qdrant_client
    
    # Seed tenant and user
    tenant = Tenant(id=uuid.uuid4(), name="Tenant Vector Scoped")
    db_session.add(tenant)
    db_session.commit()
    
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        filename="test.txt",
        status="pending",
    )
    db_session.add(doc)
    db_session.commit()
    
    # Perform ingestion
    file_bytes = b"Hello this is some text to chunk and embed."
    process_document_ingestion(
        document_id=doc.id,
        file_content=file_bytes,
        filename="test.txt",
        db_session=db_session,
    )
    
    # Verify document status updated to ready
    db_session.refresh(doc)
    assert doc.status == "ready"
    assert doc.error_message is None
    
    # Verify qdrant client upsert was called with the tenant_id in the payload
    assert mock_qdrant_client.upsert.called
    
    # Inspect arguments passed to upsert
    call_args = mock_qdrant_client.upsert.call_args[1]
    points = call_args["points"]
    assert len(points) > 0
    
    # Ensure tenant_id and document_id are in the payload of the upserted point
    payload = points[0].payload
    assert payload["tenant_id"] == str(tenant.id)
    assert payload["document_id"] == str(doc.id)


@patch("app.core.vector_store.QdrantClient")
def test_cross_tenant_vector_isolation(
    mock_qdrant_client_cls: MagicMock,
    db_session: Session,
) -> None:
    """Test that queries or searches filter at the Qdrant index level using the tenant_id."""
    mock_qdrant_client = MagicMock()
    mock_qdrant_client_cls.return_value = mock_qdrant_client
    
    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()
    
    # We will instantiate the vector store and call search_similar
    from app.core.vector_store import QdrantVectorStore
    store = QdrantVectorStore()
    
    # Call search for tenant A
    query_vector = [0.1] * 1024
    store.search_similar(tenant_id=tenant_a_id, query_vector=query_vector, limit=5)
    
    # Check that query_points was called on Qdrant client
    assert mock_qdrant_client.query_points.called
    
    # Retrieve the filters from the call args
    call_args = mock_qdrant_client.query_points.call_args[1]
    query_filter = call_args["query_filter"]
    
    # Verify that the filter restricts strictly to tenant_a_id
    # Qdrant filters structure: query_filter.must[0].key == "tenant_id", query_filter.must[0].match.value == str(tenant_a_id)
    must_conditions = query_filter.must
    assert len(must_conditions) == 1
    
    tenant_condition = must_conditions[0]
    assert tenant_condition.key == "tenant_id"
    assert tenant_condition.match.value == str(tenant_a_id)
    assert tenant_condition.match.value != str(tenant_b_id)


def test_failed_parse_sets_status_failed(db_session: Session) -> None:
    """Test that if parsing fails (e.g. corrupt format exception), document status is set to failed."""
    tenant = Tenant(id=uuid.uuid4(), name="Tenant Fail")
    db_session.add(tenant)
    db_session.commit()
    
    doc = Document(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        filename="corrupt.pdf",
        status="pending",
    )
    db_session.add(doc)
    db_session.commit()
    
    # We pass empty or corrupt PDF bytes that cause the parser to fail
    corrupt_bytes = b"NOT_A_REAL_PDF_HEADER_AND_CRASH"
    
    # Run ingestion - it should catch the parsing exception, log it, and mark document as failed
    process_document_ingestion(
        document_id=doc.id,
        file_content=corrupt_bytes,
        filename="corrupt.pdf",
        db_session=db_session,
    )
    
    db_session.refresh(doc)
    assert doc.status == "failed"
    assert doc.error_message is not None
    assert len(doc.error_message) > 0
