# Security Policy — Tenant Isolation Architecture

This document outlines the security architecture and multi-tenant isolation mechanisms implemented in EnterpriseRAG.

---

## 1. Multi-Tenant Boundary Checklist

Every commit is validated against the following security checklist before code changes are merged:

| Check Item | Design Implementation | Status |
| :--- | :--- | :---: |
| **JWT Scoped Auth** | `tenant_id` is derived strictly from the cryptographically verified JWT access token payload, never from user-supplied query params or body fields. | **Enforced** |
| **SQL Param Scoping** | All Postgres queries filter rows using parameterized SQL bounds (`filter(Model.tenant_id == tenant_id)`). Direct SQL string concatenation is forbidden. | **Enforced** |
| **Vector Pre-Filtering** | Qdrant vector searches apply Qdrant payload filters on `tenant_id` at the index level before retrieval. No post-filtering is done in memory. | **Enforced** |
| **Upload Guardrails** | Validates content types (PDF, DOCX, TXT only) and limits maximum file uploads to a configurable boundary (default 20MB). | **Enforced** |
| **No PII Logging** | Diagnostic logs contain only process steps and latencies. Chunks, questions, and answers are omitted from system logs. | **Enforced** |

---

## 2. Technical Blueprint

### A. Authentication & Verification
- Endpoint `/auth/signup` registers a new `Tenant` organization and a first `admin` user within a single, ACID-compliant database transaction.
- Tokens are signed using `jwt_secret` (HS256) and contain `user_id`, `tenant_id`, and `role`.
- FastAPIs dependencies:
  - `get_current_user` extracts and parses JWTs.
  - `get_current_tenant_id` extracts the tenant context.
  - `require_role(role)` enforces RBAC permission blocks.

### B. Relational Layer (Postgres)
SQLAlchemy models strictly map every workspace record to a `tenant_id`:
- `User` -> `tenant_id`
- `Document` -> `tenant_id`
- `ChatMessage` -> `tenant_id`
- `QueryTrace` -> `tenant_id`

All query lookups filter by the resolved token context:
```python
db.query(Document).filter(
    Document.tenant_id == tenant_id, 
    Document.id == doc_id
).first()
```

### C. Vector Store Layer (Qdrant)
Vector isolation is achieved via payload pre-filtering. Each chunk vector payload includes `tenant_id`.
When querying or scrolling collection points, Qdrant applies payload filtering at the search execution step:
```python
from qdrant_client.http import models as q_models

filter_cond = q_models.Filter(
    must=[
        q_models.FieldCondition(
            key="tenant_id",
            match=q_models.MatchValue(value=str(tenant_id)),
        )
    ]
)
```
This pre-filtering ensures that the vector database index search only scans elements belonging to the target tenant, completely preventing cross-tenant information exposure.
