# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Catalog Intelligence Engine — internal system that ingests product catalogs, audits attribute quality, generates semantic attributes via LLMs, supports human review workflows, and exports enriched catalogs for AI shopping agents.

Target: ~1,000 SKUs in consumer tech, scaling to ~12,000.

**Status: All 8 phases complete.** See `todo.md` for the full checklist and `summary.md` for architecture overview.

## Canonical References

All schemas, business rules, API contracts, scoring thresholds, and LLM prompts live in **`specs.md`** — it is the single source of truth. The implementation plan and prompt sequence are in **`prompt_plan.md`**. The task checklist is in **`todo.md`**.

When implementing any feature, reference `specs.md` directly rather than inferring from code or comments.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.10+ / FastAPI |
| Database | PostgreSQL 15 (Cloud SQL) |
| ORM + Migrations | SQLAlchemy + Alembic |
| Validation | Pydantic v2 (`@field_validator`, `@model_validator`, `model_config`) |
| Workers | Cloud Run Jobs + Cloud Tasks |
| Frontend | Next.js 16 (App Router, TypeScript, Tailwind CSS v4) |
| Frontend Tests | Vitest + React Testing Library + jsdom |
| LLM | Vertex AI (Gemini) via injectable `GeminiClient` |
| Search | Algolia |
| Auth | Google Cloud IAP (JWT validation when `IAP_AUDIENCE` set, `X-User-Email` fallback in dev) |
| Metrics | Prometheus (`prometheus-client`) |
| Storage | Cloud Storage via injectable `StorageClient` |

## Monorepo Structure

```
repo/
  api/              # FastAPI backend (routers, services, models, dependencies, llm/)
  api/alembic/      # Alembic migrations
  api/llm/prompts/  # LLM system prompt (system.txt) and few-shot examples (few_shot.json)
  worker/           # Cloud Run Jobs (batch processing)
  ui/               # Next.js frontend (App Router)
  ui/src/test/      # Frontend tests (vitest + React Testing Library)
  infra/            # Prometheus + Grafana configs and dashboards
  tests/            # Backend tests (pytest + httpx, 100 tests)
  tests/load/       # k6 load test scripts
  cloudbuild.yaml   # Cloud Build pipeline (builds + deploys API + UI to Cloud Run)
```

## Build & Run Commands

```bash
# Backend
cd api && pip install -r requirements.txt
uvicorn api.main:app --reload

# Database migrations (run from api/ directory)
alembic upgrade head

# Lint + format
ruff check .
ruff format .

# Backend tests (stop on first failure, from project root)
PYTHONPATH=. pytest -x

# Run a single test file
PYTHONPATH=. pytest tests/test_health.py

# Run a single test function
PYTHONPATH=. pytest tests/test_health.py::test_health_endpoint -x

# Frontend
cd ui && npm install && npm run dev

# Frontend tests
cd ui && npx vitest run

# Load test (requires k6 installed)
k6 run tests/load/k6_load_test.js
```

### Test DB Prerequisites

Tests require a running PostgreSQL instance. Default credentials: `catalog:catalog@localhost:5432/catalog_engine_test`. Override with `DATABASE_URL_TEST` env var. The test harness creates/drops all tables per test and wraps each test in a rolled-back transaction (see `tests/conftest.py`).

The dev DB defaults to `catalog:catalog@localhost:5432/catalog_engine` (see `api/config.py`).

## Architecture

### Data Flow

```
Catalog Sources -> Ingestion (POST /ingest/jobs) -> Canonical Product DB
  -> Audit Engine (POST /audit/run) -> Audit Results
  -> LLM Enrichment (POST /skus/{id}/enrich) -> Enrichment Versions (PENDING_REVIEW)
  -> Human Review (POST /skus/{id}/review) -> Approved Versions
  -> Export (GET /exports/latest) + Algolia Sync (POST /algolia/sync)
```

### Immutable Version History

Enrichment versions are append-only. Every LLM run or human edit creates a new `enrichment_version` with a `parent_version_id` linking to its predecessor. Review state is 1:1 with versions. Only `APPROVED` versions appear in exports.

### Auth & Roles

Three roles: `ADMIN`, `REVIEWER_GENERAL`, `REVIEWER_CATEGORY`. Category reviewers are restricted server-side to their assigned category. Auth uses `get_current_user` dependency (`api/dependencies/auth.py`): validates IAP JWT when `IAP_AUDIENCE` env var is set, falls back to `X-User-Email` header in dev. Role enforcement via `require_role(*roles)` dependency. In tests, use `auth_headers(email)` helper.

### External Clients (Injectable Dependencies)

All external services follow the same pattern: abstract base class + concrete implementation + get/set functions for dependency injection.

| Client | Abstract | Concrete | Dependency |
|---|---|---|---|
| LLM | `LLMClient` (`api/llm/base.py`) | `GeminiClient` (`api/llm/gemini_client.py`) | `api/dependencies/llm.py` |
| Algolia | `AlgoliaClient` (`api/dependencies/algolia.py`) | `RealAlgoliaClient` | `get_algolia_client()` |
| Storage | `StorageClient` (`api/dependencies/storage.py`) | `CloudStorageClient` | `get_storage_client()` |

### Middleware Stack (applied in `api/main.py`)

- **CORS** — configurable via `CORS_ORIGINS` env var (comma-separated, defaults to `http://localhost:3000`)
- **RequestLogger** — logs method, path, status, duration with user context (skips `/health`, `/metrics`)
- **GlobalErrorHandler** — catches unhandled exceptions → JSON 500 response
- **RateLimiter** — in-memory sliding window per path prefix per client (`X-User-Email` or IP)

### Metrics & Observability

Prometheus metrics exposed at `GET /metrics` (see `api/metrics.py`):
- `catalog_skus_processed_total` — counter by operation (ingestion/audit/enrichment)
- `catalog_llm_calls_total` / `catalog_llm_latency_seconds` — LLM success/failure rate and latency
- `catalog_request_latency_seconds` — HTTP request latency histogram by method/path
- `catalog_pending_review_count` — gauge updated on dashboard stats queries
- `catalog_time_to_approval_seconds` — summary of review turnaround time
- `catalog_review_actions_total` — counter by action (approve/reject/escalate/etc.)

Structured JSON logging via `StructuredFormatter` with context fields: `job_id`, `sku_id`, `version_id`, `user_email`, `duration_ms`.

## Tests

**Backend:** 100 tests across 12 files. Run with `PYTHONPATH=. pytest -x` from project root. Tests use a real Postgres test DB (`catalog_engine_test`) with per-test transaction rollback. Fixtures in `tests/conftest.py`. `auth_headers(email)` helper for auth header injection.

**Frontend:** 29 tests across 3 files. Run with `cd ui && npx vitest run`. Uses jsdom environment with mocked API calls and Next.js navigation.

**Load:** k6 script at `tests/load/k6_load_test.js` — 5 phases covering ingestion (1,000 SKUs), audit, enrichment, review, and export.

## Key Conventions

- All external clients (LLM, Algolia, Cloud Storage) must be injectable dependencies, mockable in tests
- Use Pydantic v2 conventions: `@field_validator`, `@model_validator`, `model_config` (not v1 `Config` class)
- Enums (`RoleEnum`, `SourceEnum`, etc.) are Python/SQLAlchemy enums, not standalone DB tables
- `DATABASE_URL` always from environment, never hardcoded
- Single item failures in batch operations must not rollback the entire batch
- JSON schema validation on all LLM output before persisting
- Structured logs must include context fields via `extra={}`

## Linting

Ruff is configured in `pyproject.toml` with rules E (errors), F (pyflakes), I (import sorting). Line length 100.

## CI

GitHub Actions workflow in `.github/workflows/ci.yml` runs on push/PR to main:
- `lint` job: ruff check + format check
- `test` job: pytest against a Postgres 15 service container

## Deployment

Cloud Build pipeline in `cloudbuild.yaml` builds and deploys both API and UI to Cloud Run:
- Runs Alembic migrations before deploy
- Mounts secrets from Secret Manager as env vars (`--update-secrets`)
- Connects to Cloud SQL via built-in proxy (`--add-cloudsql-instances`)

## Monitoring

Local monitoring stack via `docker-compose.monitoring.yml`:
```bash
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up
```
- Prometheus at `localhost:9090` scrapes `/metrics` every 15s
- Grafana at `localhost:3001` (admin/admin) with pre-provisioned dashboard for all 7 catalog metrics
