import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt  # type: ignore[import-untyped]
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.database import get_db
from app.models.user import User

settings = get_settings()
security = HTTPBearer()


def create_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> str:
    """Generate a JWT access token containing user, tenant, and role claims.
    
    Args:
        user_id: The UUID of the authenticated user.
        tenant_id: The UUID of the user's tenant/organization.
        role: The user's role (admin or member).
        
    Returns:
        Encoded JWT token as a string.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "exp": expire,
    }
    return jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode a JWT access token and return its claims payload.
    
    Raises:
        HTTPException: 401 status code if validation fails.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency to retrieve the currently authenticated user from the token.
    
    Scopes user retrieval by tenant_id extracted from the token claims.
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    
    user_id_str = payload.get("sub")
    tenant_id_str = payload.get("tenant_id")
    
    if not user_id_str or not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = uuid.UUID(user_id_str)
        tenant_uuid = uuid.UUID(tenant_id_str)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload structure",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    # Query the user ensuring tenant scope matches
    user = db.query(User).filter_by(id=user_uuid, tenant_id=tenant_uuid).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or invalid tenant scope",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_current_tenant_id(user: User = Depends(get_current_user)) -> uuid.UUID:
    """FastAPI dependency that returns the active tenant_id.
    
    This is the SINGLE, non-overridable source of tenant_id for all endpoints.
    Never accepts tenant_id from request body or query parameters.
    """
    return user.tenant_id


def require_role(required_role: str) -> Callable[[User], User]:
    """Dependency factory for Role-Based Access Control (RBAC).
    
    Args:
        required_role: The role required to access the endpoint (e.g. 'admin').
        
    Returns:
        A dependency function that checks user role.
    """
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted for this role",
            )
        return user
    return dependency
