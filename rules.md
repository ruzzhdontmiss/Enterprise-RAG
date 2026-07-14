# Project Rules — Multi-Tenant Enterprise RAG Platform

## 1. Project Identity
You are building "EnterpriseRAG" — a multi-tenant Retrieval-Augmented Generation
platform. Multiple organizations (tenants) each have isolated knowledge bases.
Users chat with their org's documents and get grounded, cited answers.

Optimize for: correctness > security > readability > cleverness > speed.
This is a portfolio project — code quality and architecture clarity matter
as much as working features.

## 2. Tech Stack (do not deviate without asking)
- Backend: Python 3.12, FastAPI, Pydantic v2
- Orchestration: LangGraph (bounded adaptive RAG flow — see §3)
- Vector store: Qdrant (multi-tenant via payload-based isolation, filtered at
  the index level)
- Relational store: Postgres (tenants, users, docs metadata, chat history) via
  SQLAlchemy + Alembic
- LLM + Embeddings: Mistral API — mistral-small-latest for generation,
  mistral-embed for embeddings — wrapped behind a provider interface so it's
  swappable later
- Rate-limit handling: request queue + exponential backoff (Mistral free tier
  is low-throughput); simple cache for repeated embedding calls
- Reranker: cross-encoder (bge-reranker-base) as a second-stage filter
- Auth: JWT + row-level tenant scoping, RBAC (admin/member per org)
- Frontend: Next.js + TypeScript + Tailwind + shadcn/ui, streaming responses (SSE)
- Observability: structured logging + a trace record per query (retrieval
  steps, scores, latency)
- Eval: RAGAS or a custom faithfulness/relevance scoring harness
- Infra: Docker Compose for local dev, one deploy target documented
- Tests: pytest (backend), Vitest (frontend). Mock the Mistral client in tests
  — do not burn API quota running the test suite.

## 3. Architecture Principles
- **Tenant isolation is non-negotiable.** Every query, every DB call, every
  vector search must be scoped by tenant_id. No endpoint may return
  cross-tenant data, even accidentally. Write a test for this before writing
  the feature it protects.
- RAG pipeline is modular: Ingest → Chunk → Embed → Index → Retrieve → Rerank
  → Generate → Cite. Each stage is swappable and independently testable.
- Agentic scope is intentionally bounded: query rewrite → hybrid retrieval
  (dense + BM25, reciprocal rank fusion) → rerank → single confidence-gated
  re-retrieval → generate. Do not add multi-step planning or iterative
  self-correction loops without explicit approval — scope creep here risks an
  unfinished demo.
- All LLM outputs that reference documents must include verifiable citations
  (chunk id + source doc + page/section). No answer without grounding.
- No secrets in code. All config via environment variables, validated at
  startup with Pydantic Settings.

## 4. Coding Standards
- Type hints everywhere (Python) / strict TypeScript (frontend). No `any`, no
  bare `except:`.
- Every public function/endpoint has a docstring stating inputs, outputs, and
  tenant-scoping behavior.
- Errors are typed and handled explicitly — no silent failures in the RAG
  pipeline; log retrieval misses and low-confidence generations.
- Small, single-purpose functions. If a function does ingestion AND embedding,
  split it.
- Commit in small, logical units. Conventional commits (feat:, fix:, refactor:).

## 5. Security & Multi-Tenancy Checklist (self-check before marking done)
- [ ] tenant_id derived from auth token, never from client-supplied body/query param
- [ ] Postgres queries use tenant_id filter (or RLS policies) — no raw SQL string concat
- [ ] Vector search filters by tenant_id at the index level, not post-filtered in app code
- [ ] File uploads validated (type, size, malware-scan stub) before ingestion
- [ ] Rate limiting on ingestion and query endpoints
- [ ] No PII/document content in logs beyond what's needed for debugging

## 6. Testing Requirements
- Unit tests for chunking, retrieval scoring, citation extraction
- Integration test: seed two tenants, prove tenant A cannot retrieve tenant B's docs
- Eval harness run against a fixed golden Q&A set on every pipeline change,
  results logged to a file so before/after numbers can go in the README
- Do not mark a feature complete without a passing test demonstrating it

## 7. What "done" looks like for each feature
1. Code + tests pass
2. Updated README section if it changes setup/usage
3. If it touches the pipeline, eval scores logged
4. No TODOs left unexplained — either fixed or filed as a GitHub issue

## 8. Build Plan (phases)
- **Phase 0 — Skeleton**: repo structure, Docker Compose, env config, health
  check, CI stub. *(current)*
- **Phase 1 — Tenancy & Auth**: tenant/user models, signup/login, JWT
  middleware, RBAC. Write the cross-tenant isolation test first.
- **Phase 2 — Ingestion Pipeline**: upload → parse → chunk → embed → store in
  Qdrant with tenant-scoped payload.
- **Phase 3 — Baseline Retrieval + Generation**: simple top-k retrieve →
  prompt → generate with citations. Get a demoable v1 fast.
- **Phase 4 — Adaptive Retrieval**: query rewrite, hybrid search, rerank,
  one confidence-gated re-retrieval (see §3 for scope boundary).
- **Phase 5 — Eval Harness**: golden dataset, faithfulness/relevance/context
  precision scoring, results logged.
- **Phase 6 — Observability**: per-query trace (chunks retrieved, scores,
  latency), simple dashboard.
- **Phase 7 — Frontend Polish**: streaming chat UI, citation hover cards,
  per-tenant admin panel.
- **Phase 8 — Deploy + Docs**: one-command deploy, architecture diagram, demo
  GIF, README results section with real eval numbers.

## 9. Agent Workflow Rules
- Before implementing a phase, restate the plan in 3-5 bullets and wait for
  confirmation if the change touches auth, tenancy, or the data model.
- Work in vertical slices (one full feature end-to-end) rather than building
  all backend then all frontend.
- When unsure about a library API, check docs/search rather than guessing.
- Never invent metrics or benchmark numbers for the README — only report what
  the eval harness actually produced.
- Ask before adding new dependencies not listed in §2.
