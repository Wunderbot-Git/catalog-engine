# Summary — Catalog Intelligence Engine

## What It Does

Internal system for Alkosto (Colombian retailer) that takes raw product catalog data and enriches it with AI-generated semantic attributes (use case tags, persona tags, trust signals, agent summaries) and flags missing product attributes to power AI shopping agents.

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Catalog      │───▶│  FastAPI      │───▶│  PostgreSQL   │
│  Sources      │    │  Backend      │    │  (Cloud SQL)  │
│  (JSON/CSV)   │    │              │    │              │
└──────────────┘    └──────┬───────┘    └──────────────┘
                           │
                    ┌──────┴───────┐
                    │              │
               ┌────▼────┐  ┌─────▼─────┐
               │ Vertex AI│  │  Next.js   │
               │ (Gemini) │  │  Frontend  │
               │  LLM     │  │            │
               └────┬────┘  └───────────┘
                    │
               ┌────▼────┐  ┌───────────┐
               │ Algolia  │  │   Cloud    │
               │ Search   │  │  Storage   │
               └─────────┘  └───────────┘
```

## Data Pipeline

1. **Ingest** — `POST /ingest/jobs` accepts batched product data, upserts into `products` table
2. **Audit** — `POST /audit/run` scores each SKU for completeness and richness, assigns enrichment priority (HIGH/MEDIUM/LOW)
3. **Enrich** — `POST /skus/{id}/enrich` sends product context to Gemini LLM, creates an immutable `enrichment_version` with semantic attributes
4. **Review** — `POST /skus/{id}/review` supports approve, approve with edits, reject, escalate, comment, re-enrich actions
5. **Export** — `GET /exports/latest` returns all approved versions; `POST /algolia/sync` pushes to Algolia search index

## Key Design Decisions

- **Immutable version history**: Every enrichment (LLM or human) creates a new version linked to its parent. Review state is 1:1 with versions. This provides full audit trail.
- **Injectable external clients**: LLM, Algolia, and Cloud Storage all follow abstract base + concrete implementation + FastAPI dependency injection pattern. This makes testing trivial.
- **Dual-mode auth**: `IAP_AUDIENCE` env var controls whether Cloud IAP JWT validation is active (production) or `X-User-Email` header fallback is used (development).
- **Category-scoped reviewers**: `REVIEWER_CATEGORY` users can only see and act on SKUs in their assigned category, enforced server-side.

## API Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Health check |
| GET | `/metrics` | None | Prometheus metrics |
| GET | `/me` | Any | Current user info |
| GET | `/skus` | Any | List SKUs with filters/pagination |
| GET | `/skus/{id}` | Any | SKU detail with latest enrichment + audit |
| POST | `/ingest/jobs` | ADMIN | Batch ingest products |
| POST | `/audit/run` | ADMIN | Run audit scoring |
| POST | `/skus/{id}/enrich` | ADMIN, REVIEWER_GENERAL | LLM enrichment |
| POST | `/skus/{id}/review` | Any (category-scoped) | Review actions |
| GET | `/skus/{id}/versions` | Any | Version history |
| GET | `/skus/{id}/comments` | Any | Comment thread |
| GET | `/exports/latest` | ADMIN | Export approved versions |
| POST | `/algolia/sync` | ADMIN | Sync to Algolia |
| GET | `/dashboard/stats` | Any | Dashboard statistics |
| POST | `/admin/users/{id}/roles` | ADMIN | Assign role |
| DELETE | `/admin/users/{id}/roles` | ADMIN | Remove role |
| GET | `/admin/users` | ADMIN | List users |
| PUT | `/admin/assignments/{sku_id}` | ADMIN | Reassign SKU |
| GET | `/admin/audit/thresholds` | ADMIN | Get thresholds |
| PUT | `/admin/audit/thresholds` | ADMIN | Update thresholds |

## Frontend Pages

- **Dashboard** (`/dashboard`) — Stats cards, throughput chart, rejection reasons chart, filterable SKU table with keyboard navigation. Category reviewers see a locked category filter.
- **Review Workspace** (`/skus/[skuId]`) — Product panel, audit scores, editable enrichment fields (chip inputs for tags, structured trust signals, summary with character counter), action bar (approve/reject/escalate/re-enrich), version history with side-by-side diff, comments tab, keyboard shortcuts.
- **Admin Panel** (`/admin`) — User management with role assignment, SKU reassignment, audit threshold configuration with confirmation modal.

## Test Coverage

| Layer | Tests | Runner | Details |
|---|---|---|---|
| Backend | 107 | pytest + httpx | 12 test files, per-test DB transaction rollback |
| Frontend | 33 | vitest + RTL | 3 test files, jsdom environment, mocked API |
| Load | 1 script | k6 | 5 phases, 1,000 SKU scale validation |

## Metrics (Prometheus)

| Metric | Type | Labels |
|---|---|---|
| `catalog_skus_processed_total` | Counter | `operation` |
| `catalog_llm_calls_total` | Counter | `outcome` |
| `catalog_llm_latency_seconds` | Histogram | — |
| `catalog_request_latency_seconds` | Histogram | `method`, `path` |
| `catalog_pending_review_count` | Gauge | — |
| `catalog_time_to_approval_seconds` | Summary | — |
| `catalog_review_actions_total` | Counter | `action` |

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `DATABASE_URL_TEST` | Tests only | Test DB connection string |
| `IAP_AUDIENCE` | Production | Cloud IAP audience for JWT validation |
| `ALGOLIA_APP_ID` | For sync | Algolia application ID |
| `ALGOLIA_API_KEY` | For sync | Algolia admin API key |
| `ALGOLIA_INDEX_NAME` | For sync | Algolia index name |
| `EXPORT_BUCKET` | For export | Cloud Storage bucket name |

## Remaining Operational Tasks

> Deploy configs and monitoring are ready. These are the remaining manual steps:

- Run k6 load test against staging environment
- Deploy to Cloud Run with production secrets configured
