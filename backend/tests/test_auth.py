from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
import uuid

from app.main import app
from app.models.tenant import Tenant
from app.models.user import User
from app.core.security import get_password_hash
from app.core.auth import create_access_token

client = TestClient(app)


def test_signup_creates_tenant_and_admin_user(db_session: Session) -> None:
    """Test that signing up creates a tenant and an admin user in one transaction."""
    payload = {
        "tenant_name": "Acme Corp",
        "email": "admin@acme.com",
        "password": "securepassword123",
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 201
    
    data = response.json()
    assert "access_token" in data
    assert "user" in data
    assert data["user"]["email"] == "admin@acme.com"
    assert data["user"]["role"] == "admin"
    assert "tenant_id" in data["user"]
    
    # Check database directly
    tenant = db_session.query(Tenant).filter_by(name="Acme Corp").first()
    assert tenant is not None
    user = db_session.query(User).filter_by(email="admin@acme.com").first()
    assert user is not None
    assert user.tenant_id == tenant.id
    assert user.role == "admin"


def test_login_returns_valid_token(db_session: Session) -> None:
    """Test that logging in with valid credentials returns a valid access token."""
    # Seed a tenant and user
    tenant = Tenant(id=uuid.uuid4(), name="Beta LLC")
    db_session.add(tenant)
    db_session.commit()
    
    hashed_pwd = get_password_hash("password123")
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="user@beta.com",
        hashed_password=hashed_pwd,
        role="member",
    )
    db_session.add(user)
    db_session.commit()

    # Call login
    payload = {
        "email": "user@beta.com",
        "password": "password123",
    }
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 200
    
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_me_requires_auth() -> None:
    """Test that the /auth/me endpoint requires authentication."""
    response = client.get("/auth/me")
    assert response.status_code == 401


def test_cross_tenant_isolation(db_session: Session) -> None:
    """Test that tenant A's token cannot read tenant B's data through any endpoint.
    
    Specifically:
    1. Tenant A's token fetches /auth/me and returns Tenant A's details, not Tenant B's.
    2. Tenant A's token fetches /auth/tenant-users and only sees users of Tenant A, not Tenant B.
    """
    # Seed Tenant A and User A (admin)
    tenant_a = Tenant(id=uuid.uuid4(), name="Tenant A")
    db_session.add(tenant_a)
    db_session.commit()
    
    user_a = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="admin@a.com",
        hashed_password=get_password_hash("passwordA"),
        role="admin",
    )
    db_session.add(user_a)
    db_session.commit()
    
    # Seed Tenant B and User B (admin)
    tenant_b = Tenant(id=uuid.uuid4(), name="Tenant B")
    db_session.add(tenant_b)
    db_session.commit()
    
    user_b = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email="admin@b.com",
        hashed_password=get_password_hash("passwordB"),
        role="admin",
    )
    db_session.add(user_b)
    db_session.commit()

    # Generate token for User A
    token_a = create_access_token(user_id=user_a.id, tenant_id=tenant_a.id, role=user_a.role)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Fetch /auth/me as User A
    response_me = client.get("/auth/me", headers=headers_a)
    assert response_me.status_code == 200
    data_me = response_me.json()
    assert data_me["email"] == "admin@a.com"
    assert uuid.UUID(data_me["tenant_id"]) == tenant_a.id
    assert uuid.UUID(data_me["tenant_id"]) != tenant_b.id

    # Fetch /auth/tenant-users as User A
    response_users = client.get("/auth/tenant-users", headers=headers_a)
    assert response_users.status_code == 200
    users_list = response_users.json()
    
    # Verify we only see Tenant A's users, not Tenant B's
    emails = [u["email"] for u in users_list]
    assert "admin@a.com" in emails
    assert "admin@b.com" not in emails


def test_role_enforcement(db_session: Session) -> None:
    """Test that a member role cannot hit an admin-only route."""
    tenant = Tenant(id=uuid.uuid4(), name="Test Org")
    db_session.add(tenant)
    db_session.commit()
    
    # Admin user
    admin_user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="admin@test.com",
        hashed_password=get_password_hash("pwd"),
        role="admin",
    )
    db_session.add(admin_user)
    
    # Member user
    member_user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email="member@test.com",
        hashed_password=get_password_hash("pwd"),
        role="member",
    )
    db_session.add(member_user)
    db_session.commit()

    # Admin client
    admin_token = create_access_token(user_id=admin_user.id, tenant_id=tenant.id, role="admin")
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Member client
    member_token = create_access_token(user_id=member_user.id, tenant_id=tenant.id, role="member")
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Admin calls admin-only route
    response_admin = client.get("/auth/admin-only", headers=admin_headers)
    assert response_admin.status_code == 200

    # Member calls admin-only route
    response_member = client.get("/auth/admin-only", headers=member_headers)
    assert response_member.status_code == 403


def test_database_url_prefix_rewrite() -> None:
    """Test that Settings database_url validator rewrites driver scheme prefixes correctly."""
    from app.config import Settings
    
    # 1. postgresql:// prefix should rewrite
    s1 = Settings(database_url="postgresql://db_user:pwd@db_host:5432/db_name")
    assert s1.database_url == "postgresql+psycopg://db_user:pwd@db_host:5432/db_name"
    
    # 2. postgres:// prefix should rewrite
    s2 = Settings(database_url="postgres://db_user:pwd@db_host:5432/db_name")
    assert s2.database_url == "postgresql+psycopg://db_user:pwd@db_host:5432/db_name"
    
    # 3. Correct prefix should not change (no-op)
    s3 = Settings(database_url="postgresql+psycopg://db_user:pwd@db_host:5432/db_name")
    assert s3.database_url == "postgresql+psycopg://db_user:pwd@db_host:5432/db_name"
