import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.auth import (
    create_access_token,
    get_current_tenant_id,
    get_current_user,
    require_role,
)
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


# Pydantic Schemas
class SignupRequest(BaseModel):
    tenant_name: str
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    email: str
    role: str


class SignupResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, db: Session = Depends(get_db)):
    """Sign up a new Tenant and their initial Administrator User.
    
    This is executed in a single atomic transaction.
    """
    # Check if user already exists globally
    existing_user = db.query(User).filter_by(email=payload.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists",
        )

    try:
        # Create Tenant
        tenant = Tenant(name=payload.tenant_name)
        db.add(tenant)
        db.flush()  # Extract the newly created tenant UUID

        # Create Admin User associated with the Tenant
        hashed_pwd = get_password_hash(payload.password)
        user = User(
            tenant_id=tenant.id,
            email=payload.email,
            hashed_password=hashed_pwd,
            role="admin",  # First user created in signup is the tenant admin
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create tenant organization: {str(e)}",
        ) from e

    # Generate access token
    token = create_access_token(user_id=user.id, tenant_id=tenant.id, role=user.role)
    return SignupResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate credentials and return a scoped JWT access token."""
    user = db.query(User).filter_by(email=payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    return LoginResponse(access_token=token)


@router.get("/me", response_model=UserOut)
def read_me(current_user: User = Depends(get_current_user)):
    """Retrieve details of the currently authenticated user."""
    return current_user


@router.get("/tenant-users", response_model=List[UserOut])
def get_tenant_users(
    tenant_id: uuid.UUID = Depends(get_current_tenant_id),
    db: Session = Depends(get_db),
):
    """Retrieve all users belonging to the caller's tenant.
    
    Demonstrates active row-level tenant isolation using the tenant_id dependency.
    """
    users = db.query(User).filter_by(tenant_id=tenant_id).all()
    return users


@router.get("/admin-only", response_model=UserOut)
def admin_only_route(current_user: User = Depends(require_role("admin"))):
    """A test endpoint restricted only to users with the 'admin' role."""
    return current_user
