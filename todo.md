# todo.md

## Catalog Intelligence Engine — Roadmap

**Status: All 8 phases complete.** 100 backend tests + 29 frontend tests passing.

> Each phase maps to prompts in `prompt_plan.md`.
> Complete phases in order — later phases depend on earlier ones.
> All technical details (schemas, rules, thresholds) are in `specs.md`.

---

### Phase 1 — Foundations
> Prompt 1

- [x] monorepo structure (`api/`, `worker/`, `ui/`, `infra/`, `tests/`)
- [x] FastAPI app skeleton with `GET /health` endpoint
- [x] `Dockerfile` for API service
- [x] `docker-compose.yml` with Postgres (credentials from env only)
- [x] `.env.example` with all required env vars documented
- [x] pytest + httpx test setup
- [x] `tests/conftest.py` with shared fixtures (db_session, client, auth_headers)

---

### Phase 2 — Data Layer
> Prompt 2

- [x] `alembic init` configured to read `DATABASE_URL` from env (no hardcoded credentials)
- [x] initial migration: `alembic revision --autogenerate -m "initial_schema"`
- [x] `products` table (`sku_id` PK, `attributes_json` JSONB, `source_snapshot_json` JSONB)
- [x] `audit_results` table
- [x] `enrichment_versions` table (UUID PK, `parent_version_id` nullable self-FK)
- [x] `review_states` table (UNIQUE on `version_id`)
- [x] `review_comments` table
- [x] `assignments` table
- [x] `users` table
- [x] `RoleEnum` as Python/SQLAlchemy enum (ADMIN, REVIEWER_GENERAL, REVIEWER_CATEGORY)
- [x] `user_roles` table with composite PK `(user_id, role)`, `category` NOT NULL when role = REVIEWER_CATEGORY
- [x] all indexes per `specs.md` section 5.8
- [x] seed data script (guarded by `ENV=development`)
- [x] verify `alembic upgrade head` is idempotent in CI

---

### Phase 3 — Core API + Auth Stub
> Prompts 3, 4

- [x] `get_current_user` dependency (`api/dependencies/auth.py`) — reads from `X-User-Email` header
- [x] `require_role(*roles)` FastAPI dependency for role enforcement
- [x] `GET /skus` with pagination, category/status/priority filters, and text search
- [x] `GET /skus/{sku_id}` with product + latest enrichment + latest audit, 404 handling
- [x] Pydantic schema `ProductIngestionItem` with field names matching canonical model in `specs.md` section 4
- [x] `POST /ingest/jobs` with upsert logic (ON CONFLICT DO UPDATE)
- [x] single item failure does NOT rollback the batch
- [x] `POST /ingest/jobs` restricted to ADMIN role

---

### Phase 4 — Intelligence Layer
> Prompts 5, 6

**Audit Engine:**
- [x] `completeness_score` logic (weighted field presence per `specs.md` section 8)
- [x] `richness_score` logic (semantic quality checks)
- [x] `priority_for_enrichment` classification (HIGH / MEDIUM / LOW thresholds)
- [x] `POST /audit/run` endpoint (optional `sku_ids` filter, upserts to `audit_results`)
- [x] restricted to ADMIN role

**LLM Enrichment:**
- [x] `LLMClient` abstract interface with typed exceptions (`LLMTimeoutError`, `LLMInvalidResponseError`, `LLMSchemaValidationError`)
- [x] `GeminiClient` concrete implementation
- [x] system prompt + few-shot examples loaded from `specs.md` sections 9.5 and 9.8 at startup (not inlined in code)
- [x] `EnrichmentResult` Pydantic schema with tag deduplication, slug validation, summary length cap
- [x] JSON schema validation of LLM output before persisting
- [x] retry logic: 3 attempts with exponential backoff (1s, 2s, 4s)
- [x] `NEEDS_REVIEW` state on unrecoverable LLM failure
- [x] `confidence_score < 0.7` sets `priority_for_review = HIGH`
- [x] `POST /skus/{sku_id}/enrich` endpoint with re-enrichment support (`parent_version_id` lineage)
- [x] `GeminiClient` injectable as FastAPI dependency (mockable in tests)

---

### Phase 5 — Review System
> Prompt 7

- [x] `ReviewAction` enum (approve, approve_with_edits, reject, escalate, comment, reenrich)
- [x] `POST /skus/{sku_id}/review` endpoint
- [x] `approve`: sets APPROVED + `reviewer_id` + `reviewed_at`
- [x] `approve_with_edits`: creates new `enrichment_version` (generated_by=human, parent=llm), marks it APPROVED
- [x] `reject`: requires `rejection_reason` (422 if missing)
- [x] `escalate`: creates `assignment` for target user, sets ESCALATED
- [x] `comment`: inserts `review_comment`, does NOT change `review_state`
- [x] `reenrich`: triggers `/enrich` internally with feedback
- [x] REVIEWER_CATEGORY restriction: own category only, enforced server-side
- [x] `GET /skus/{sku_id}/versions` — full version history endpoint

---

### Phase 6 — Frontend
> Prompts 10a, 10b, 10c
> Full spec: `specs.md` section 11

**Dashboard (`/dashboard`):**
- [x] `GET /dashboard/stats` backend endpoint — backlog counts, 7-day throughput, top 5 rejection reasons
- [x] backlog count cards (PENDING_REVIEW, ESCALATED) with trend indicator
- [x] throughput sparkline (approved SKUs / last 7 days)
- [x] top 5 rejection reasons bar chart
- [x] SKU table: `sku_id`, `title`, `brand`, `category`, `priority`, `confidence_score`, `status`, `age`
- [x] column sorting: `priority`, `confidence_score`, `age`
- [x] filter bar: category, status, priority, confidence_score range, free-text search
- [x] REVIEWER_CATEGORY: category filter locked (frontend + API enforcement)
- [x] keyboard navigation: `j`/`k` rows, `Enter` open

**Review Workspace (`/skus/[sku_id]`):**
- [x] product read-only panel (title, brand, category, price, key specs)
- [x] audit panel (completeness + richness progress bars with color thresholds, missing fields)
- [x] `use_case_tags` chip input (add/remove, silent dedup, max 10)
- [x] `persona_tags` chip input (same rules)
- [x] `trust_signals` structured fields (warranty_months, certifications, sustainability_notes)
- [x] `agent_summary` textarea with live counter (yellow at 200, red + blocked at 240)
- [x] `confidence_score` read-only badge (green ≥ 0.7, yellow < 0.7)
- [x] dirty state tracking (Approve with edits only active when changes exist)
- [x] history tab: version timeline (LLM/human icons) + side-by-side diff
- [x] comments tab: thread with `comment_type` selector
- [x] action bar: Approve, Approve with edits, Reject, Re-enrich, Escalate, Save draft
- [x] auto-save to localStorage every 30s, "Draft saved" toast
- [x] keyboard shortcuts: `a` approve, `r` reject modal, `[`/`]` prev/next SKU

**Admin Panel (`/admin`):**
- [x] user list + role assignment
- [x] category assignment per user
- [x] manual SKU reassignment
- [x] audit threshold configuration

**Frontend Tests:**
- [x] `ui/src/test/dashboard.test.tsx` — 6 tests (stats cards, SKU table, filters, category lock, keyboard nav)
- [x] `ui/src/test/review_workspace.test.tsx` — 15 tests (product panel, audit, chips, review actions, escalate, comments, diff, keyboard)
- [x] `ui/src/test/admin.test.tsx` — 8 tests (user list, roles, assignment, SKU reassignment, thresholds)

---

### Phase 7 — Integrations
> Prompts 8, 9

- [x] `GET /exports/latest` — latest APPROVED version per SKU as JSON response
- [x] export writes `catalog_agent_ready.json` to Cloud Storage (`EXPORT_BUCKET`) via injectable `StorageClient`
- [x] `POST /algolia/sync` — partial upsert of enrichment fields to Algolia index
- [x] Algolia client injectable (mockable in tests)
- [x] both endpoints restricted to ADMIN role

---

### Phase 8 — Hardening

- [x] replace `get_current_user` stub with Cloud IAP JWT validation (`api/dependencies/auth.py` — validates `X-Goog-IAP-JWT-Assertion` when `IAP_AUDIENCE` is set, falls back to `X-User-Email` in dev)
- [x] structured logging infrastructure (`StructuredFormatter` in `api/logging_config.py`)
- [x] structured logging coverage: all log lines include context fields (`job_id`, `sku_id`, `version_id`, `user_email`, `duration_ms`)
- [x] metrics: `prometheus-client` with `GET /metrics` endpoint — throughput counter, LLM call/latency, request latency histogram, pending review gauge, time-to-approval summary, review action counter (`api/metrics.py`)
- [x] global FastAPI error handler returning consistent `{ "error": "...", "detail": "..." }`
- [x] rate limiting on `POST /ingest/jobs` and `POST /skus/{sku_id}/enrich`
- [x] secrets: no hardcoded secrets — all sensitive values are environment-driven (12-factor compliant); production deployment should use Secret Manager
- [x] CI pipeline (lint + tests on every push)
- [x] load test at 1,000 SKU scale (`tests/load/k6_load_test.js` — 5 phases: ingestion, audit, enrichment, review, export)

---

### Remaining Operational Tasks

> These are deployment/infrastructure tasks, not code changes.

- [x] Implement `GeminiClient._call_model` with real Vertex AI SDK (`api/llm/gemini_client.py`, prompts in `api/llm/prompts/`)
- [x] Cloud Run deploy configs (`api/Dockerfile`, `ui/Dockerfile`, `cloudbuild.yaml`, configurable CORS)
- [x] Secret Manager integration (secrets mapped in `cloudbuild.yaml` deploy step)
- [x] Prometheus/Grafana monitoring stack (`infra/`, `docker-compose.monitoring.yml`, Grafana dashboard)
- [ ] Run k6 load test against staging environment
- [ ] Deploy to Cloud Run with production secrets configured
