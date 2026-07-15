"""FastAPI application entrypoint for EnterpriseRAG."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, documents, health, query, admin
from app.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="EnterpriseRAG API",
        description="Multi-tenant Retrieval-Augmented Generation platform.",
        version="0.1.0",
    )

    # CORS is permissive in local dev only; tighten per-environment in Phase 1
    # when real frontend origins exist.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(query.router)
    app.include_router(admin.router)

    return app


app = create_app()
