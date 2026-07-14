import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import get_current_tenant_id, get_current_user
from app.core.database import get_db
from app.core.ingestion import process_document_ingestion
from app.models.document import Document
from app.models.user import User

router = APIRouter(prefix="/documents", tags=["documents"])

# Configure maximum file upload size (default to 20MB)
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    filename: str
    status: str
    uploaded_by: Optional[uuid.UUID]
    created_at: datetime
    error_message: Optional[str]


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Upload and process a document (PDF, DOCX, or TXT) for the active tenant.
    
    Verifies type and size limits before executing the ingestion pipeline.
    """
    filename = file.filename or "unknown"
    
    # 1. Validate file extension
    ext = filename.split(".")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type",
        )

    # 2. Validate file size limits
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum permitted limit (20MB)",
        )

    # 3. Create document tracking record in a pending state
    db_doc = Document(
        tenant_id=tenant_id,
        filename=filename,
        status="pending",
        uploaded_by=current_user.id,
    )
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    # 4. Trigger ingestion pipeline synchronously for now
    process_document_ingestion(
        document_id=db_doc.id,
        file_content=content,
        filename=filename,
        db_session=db,
    )

    db.refresh(db_doc)
    return db_doc


@router.get("", response_model=List[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
):
    """Retrieve lists of documents uploaded by the authenticated tenant."""
    docs = db.query(Document).filter_by(tenant_id=tenant_id).all()
    return docs
