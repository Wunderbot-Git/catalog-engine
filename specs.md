# specs.md

## Catalog Intelligence Engine — System Specification (V1)

---

## 1. System Overview

Internal system that:
1. Ingests products from multiple catalog sources (JSON, CSV, Excel, Algolia)
2. Audits attribute quality per SKU
3. Generates semantic attributes using LLMs
4. Enables human review per SKU with full version history
5. Exports an enriched catalog ready for AI shopping agents and intelligent search

**Initial target:** ~1,000 SKUs in consumer tech. Expansion to ~12,000 SKUs.

---

## 2. Tech Stack

| Layer | Technology |
|---|---|
| Backend API | Python + FastAPI |
| Database | PostgreSQL (Cloud SQL) |
| ORM + Migrations | SQLAlchemy + Alembic |
| Workers | Cloud Run Jobs + Cloud Tasks |
| Frontend | Next.js (App Router, TypeScript, Tailwind CSS) |
| LLM | Vertex AI (Gemini) |
| Search | Algolia |
| Auth | Google Cloud IAP |
| Storage | Cloud Storage |
| Hosting | Cloud Run |

---

## 3. System Flow

```
Catalog Sources (JSON, CSV, Excel, Algolia)
        ↓
  Ingestion Service
        ↓
  Canonical Product DB
        ↓
  Attribute Audit Engine
        ↓
  LLM Enrichment Engine
        ↓
  Human Review UI
        ↓
  Approved Enrichment Store
        ↓
  Export JSON  +  Algolia Sync
```

**Batch ingestion detail:**
```
[JSON/CSV/XLSX] -> [Normalizer] -> [Canonical DB] -> [Audit] -> [LLM] -> [Review UI]
                                         |                                     |
                                         v                                     v
                                    [Audit DB]                   [Versioned Enrichment DB]
                                                                               |
                                                                               v
                                                                  [Export JSON] + [Algolia Sync]
```

**Re-enrichment from UI:**
```
Reviewer -> (Re-enrich + feedback) -> Enrichment Job -> New Version (PENDING_REVIEW) -> Reviewer
```

---

## 4. Canonical Product Model

All sources are normalized to this model before any further processing.

```json
{
  "sku_id": "string",
  "title": "string",
  "brand": "string",
  "category": "string",
  "price": 0.0,
  "attributes": {},
  "source": "json|csv|excel|algolia",
  "source_snapshot": {}
}
```

**Ingestion normalization rules:**
- Field mapping per category (mapping tables)
- Unit cleaning (GB, inches, mAh, etc.)
- Type coercion (string / number / boolean)
- Minimum validation: `sku_id`, `title`, `category`, `price` are required

---

## 5. Data Model

### 5.1 `products`
Canonical SKU — the normalized base version of a product.

| Field | Type | Notes |
|---|---|---|
| `sku_id` | string PK | |
| `title` | string | |
| `brand` | string | |
| `category` | string | |
| `price` | float | |
| `attributes_json` | JSONB | all product attributes |
| `source` | enum | json \| csv \| excel \| algolia |
| `source_snapshot_json` | JSONB | original raw payload |
| `updated_at` | timestamp | |

---

### 5.2 `audit_results`
Audit output per SKU run.

| Field | Type | Notes |
|---|---|---|
| `audit_id` | PK | |
| `sku_id` | FK → products | |
| `completeness_score` | float 0..1 | |
| `richness_score` | float 0..1 | |
| `missing_critical_fields` | JSONB array | |
| `low_quality_fields` | JSONB array | |
| `priority_for_enrichment` | enum | HIGH \| MEDIUM \| LOW |
| `created_at` | timestamp | |

---

### 5.3 `enrichment_versions`
Every LLM run or human edit creates a new version. Never mutate existing versions.

| Field | Type | Notes |
|---|---|---|
| `version_id` | UUID PK | |
| `sku_id` | FK → products | |
| `parent_version_id` | UUID FK nullable | self-reference for lineage |
| `generated_by` | enum | llm \| human \| system |
| `model_name` | string nullable | e.g. gemini-pro |
| `prompt_version` | string nullable | |
| `use_case_tags` | JSONB array | |
| `persona_tags` | JSONB array | |
| `trust_signals` | JSONB object | |
| `agent_summary` | text | max 240 chars |
| `confidence_score` | float | |
| `evidence_fields` | JSONB array | fields from input that support the enrichment |
| `suggested_attributes` | JSONB array | attributes the product is missing (see 9.2.1) |
| `created_at` | timestamp | |

---

### 5.4 `review_states`
Review status associated with a single enrichment version.

| Field | Type | Notes |
|---|---|---|
| `review_id` | PK | |
| `version_id` | FK → enrichment_versions | UNIQUE — one state per version |
| `review_status` | enum | PENDING_REVIEW \| APPROVED \| REJECTED \| ESCALATED \| NEEDS_REVIEW |
| `reviewer_id` | FK → users nullable | null if auto-generated |
| `reviewed_at` | timestamp nullable | |
| `rejection_reason` | text nullable | required when REJECTED |
| `priority_for_review` | enum | HIGH \| MEDIUM \| LOW |
| `escalated` | bool | |
| `created_at` | timestamp | |

**Note on NEEDS_REVIEW:** set when LLM fails after all retries. Distinct from PENDING_REVIEW (which means awaiting human action on a valid LLM output).

---

### 5.5 `review_comments`
Comments and feedback per SKU/version.

| Field | Type | Notes |
|---|---|---|
| `comment_id` | PK | |
| `sku_id` | FK → products | |
| `version_id` | FK → enrichment_versions | |
| `author_id` | FK → users | |
| `comment_type` | enum | NOTE \| PROMPT_FEEDBACK \| QUALITY_FLAG |
| `body` | text | |
| `created_at` | timestamp | |

---

### 5.6 `assignments`
Work queue / assignment per SKU.

| Field | Type | Notes |
|---|---|---|
| `assignment_id` | PK | |
| `sku_id` | FK → products | |
| `category` | string | redundant for fast queries |
| `assigned_role` | enum | GENERAL \| CATEGORY |
| `assigned_to_user_id` | FK → users nullable | null = open queue item |
| `status` | enum | OPEN \| IN_PROGRESS \| DONE |
| `priority` | enum | HIGH \| MEDIUM \| LOW |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

Assignment rules:
- REVIEWER_CATEGORY: sees only OPEN assignments for their category
- REVIEWER_GENERAL: can open any SKU; can "take" an assignment → IN_PROGRESS

---

### 5.7 `users`, `user_roles`

**users:** `id` (UUID PK), `name`, `email` (UNIQUE), `active` (bool), `created_at`

**RoleEnum (Python/SQLAlchemy enum — not a standalone table):** `ADMIN` | `REVIEWER_GENERAL` | `REVIEWER_CATEGORY`

**user_roles:**
- Composite PK: `(user_id, role)`
- `user_id` (FK → users)
- `role` (RoleEnum)
- `category` (string, required and NOT NULL when role = REVIEWER_CATEGORY, NULL otherwise)

---

### 5.8 Indexes

| Index | Reason |
|---|---|
| `products(category)` | filter by category |
| `enrichment_versions(sku_id, created_at DESC)` | latest version per SKU |
| `review_states(review_status, created_at)` | queue filtering |
| `audit_results(priority_for_enrichment, created_at)` | prioritization |
| `assignments(category, status, priority)` | reviewer queue |

---

### 5.9 Key business rules

- Every LLM enrichment creates a version with `generated_by=llm` → state `PENDING_REVIEW`
- "Approve with edits" creates a new version with `generated_by=human`, `parent_version_id` pointing to the LLM version → state `APPROVED`
- Re-enrich creates a new LLM version with `parent_version_id` = latest version (llm or human) → state `PENDING_REVIEW`
- LLM failure after all retries → state `NEEDS_REVIEW`
- Only `APPROVED` versions are included in exports and Algolia sync
- Latest approved version per SKU = `MAX(created_at) WHERE review_status = APPROVED`

---

## 6. API Reference

All endpoints require auth header `X-User-Email` (IAP-injected in production).

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | Health check |
| GET | `/skus` | any role | List SKUs with filters + pagination |
| GET | `/skus/{sku_id}` | any role | Single SKU with latest enrichment + audit |
| GET | `/skus/{sku_id}/versions` | any role | Full version history |
| POST | `/ingest/jobs` | ADMIN | Batch upsert products |
| POST | `/audit/run` | ADMIN | Run audit engine |
| POST | `/skus/{sku_id}/enrich` | ADMIN, REVIEWER_GENERAL | Trigger LLM enrichment |
| POST | `/skus/{sku_id}/review` | ADMIN, REVIEWER_* | Submit review action |
| GET | `/exports/latest` | ADMIN | Export approved catalog as JSON |
| POST | `/algolia/sync` | ADMIN | Sync approved enrichments to Algolia |
| GET | `/dashboard/stats` | any role | Backlog counts, throughput, rejection reasons |
| GET | `/admin/users` | ADMIN | List all users with roles |
| POST | `/admin/users/{user_id}/roles` | ADMIN | Assign role to user |
| DELETE | `/admin/users/{user_id}/roles` | ADMIN | Remove role from user |
| PUT | `/admin/assignments/{sku_id}` | ADMIN | Reassign SKU to user |
| PUT | `/admin/audit/thresholds` | ADMIN | Update audit scoring thresholds |

**GET /skus — query params:**
- `category` (string)
- `status` (PENDING_REVIEW | APPROVED | REJECTED | ESCALATED | NEEDS_REVIEW)
- `priority` (HIGH | MEDIUM | LOW)
- `search` (string — matches sku_id or title)
- `page` (int, default 1)
- `page_size` (int, default 20, max 100)

---

## 7. Roles & Permissions

### ADMIN
- Manage users, roles, categories
- Reassign SKUs
- Trigger batch enrichment
- Run audit
- Export catalog + sync Algolia
- Configure thresholds and prompt versions

### REVIEWER_GENERAL
- Browse all SKUs across all categories
- Review, edit, approve, reject, escalate, re-enrich any SKU
- "Take" open assignments to help queues

### REVIEWER_CATEGORY
- Sees automatic queue filtered to their assigned category
- Review, edit, approve, reject, escalate, re-enrich SKUs in own category only
- Category restriction enforced server-side (not just in UI)

---

## 8. Audit Engine

### completeness_score (0.0–1.0) — weighted field presence

| Field | Weight |
|---|---|
| `title` non-empty | 0.20 |
| `brand` non-empty | 0.15 |
| `category` non-empty | 0.15 |
| `price` >= 0 | 0.15 |
| `attributes` has >= 1 key | 0.35 |

### richness_score (0.0–1.0) — semantic quality

| Check | Points |
|---|---|
| `title` length >= 30 chars | 0.25 |
| `attributes` has >= 5 keys | 0.25 |
| At least one attribute value is a number | 0.25 |
| `brand` contains >= 2 words | 0.25 |

### priority_for_enrichment
- **HIGH:** `completeness_score < 0.6` OR `richness_score < 0.5`
- **MEDIUM:** `completeness_score < 0.8` OR `richness_score < 0.7`
- **LOW:** otherwise

---

## 9. LLM Enrichment Engine

### 9.1 LLMClient interface

```python
class LLMTimeoutError(Exception): pass
class LLMInvalidResponseError(Exception): pass
class LLMSchemaValidationError(Exception): pass

class LLMClient(ABC):
    @abstractmethod
    async def enrich(
        self,
        product: ProductContext,
        category_context: CategoryContext,
    ) -> EnrichmentResult: ...
```

`GeminiClient` is the concrete implementation. It must be injectable as a dependency (mockable in tests).

### 9.2 Enriched attributes schema

```json
{
  "sku_id": "string",
  "use_case_tags": ["string"],
  "persona_tags": ["string"],
  "trust_signals": {
    "warranty_months": null,
    "certifications": [],
    "sustainability_notes": ""
  },
  "agent_summary": "string (max 240 chars)",
  "confidence_score": 0.0,
  "evidence_fields": [],
  "suggested_attributes": [
    { "key": "string", "value": null, "source": "product_text | missing", "reason": "string" }
  ]
}
```

#### 9.2.1 Suggested attributes

The LLM also flags structured attributes a shopper in the category would expect but that are not keys in `product.attributes`:

| `source` | Meaning | `value` |
|---|---|---|
| `product_text` | The value is stated explicitly in the title or another input field but is not a structured attribute yet | Required; copied from the input text |
| `missing` | The input has no data for it; the catalog team must source it | Must be `null` |

Suggestions are a catalog-quality signal for reviewers. They are stored on the version and editable in the review workspace, but they are **not** included in exports or Algolia sync.

### 9.3 Tag validation rules
- Tags deduped and slugified (`snake_case`) before persisting
- Max 10 tags per list
- `agent_summary` max 240 characters
- `confidence_score` must be 0.0–1.0
- `suggested_attributes`: `key` slugified to `snake_case`, deduped by key (first wins), max 10; `value` must be null for `missing` and non-empty for `product_text`
- Suggestions whose `key` already exists in `product.attributes` are dropped before persisting

### 9.4 Error handling

| Failure | Action |
|---|---|
| Timeout | Retry 3× with exponential backoff: 1s, 2s, 4s |
| Non-JSON response | Log raw, raise `LLMInvalidResponseError` |
| Schema validation fail | Log raw + error, raise `LLMSchemaValidationError` |
| All retries exhausted | Create version, set `review_state = NEEDS_REVIEW` |
| `confidence_score < 0.7` | Set `priority_for_review = HIGH` |

### 9.5 LLM System Prompt (canonical)

> This is the single source of truth. Do not derive prompt logic from any other file.

```
You are an expert in consumer electronics and e-commerce catalog optimization.

Your task is to generate semantic attributes that help AI shopping agents
understand product use cases without relying on keyword matching.

Rules:
1. Return ONLY valid JSON. No preamble, no explanation, no markdown code fences.
2. Never invent specifications not explicitly present in the input.
3. Use snake_case for all tag values.
4. If a data point is absent from the input, do not assume it — leave the
   field empty or use the default value specified in the schema.
5. agent_summary must be 1–2 sentences, maximum 240 characters.
6. confidence_score must reflect how much of the output is supported by
   explicit product data (0.0 = pure guess, 1.0 = fully supported).
7. suggested_attributes lists up to 10 structured attributes that a shopper in
   this category would expect but that are NOT already keys in
   product.attributes. Order them by how much they matter for a purchase
   decision. Each item has:
   - key: snake_case attribute name (e.g. display_inches, operating_system).
   - source: "product_text" when the value is stated explicitly in the title
     or another input field but is not yet a structured attribute; the value
     must be copied from that text, never inferred.
   - source: "missing" when the input does not state the value; value must
     be null. Never guess a value.
   - value: the extracted value for "product_text", null for "missing".
   - reason: one short sentence on why it matters or where it was found.
```

### 9.6 Controlled Vocabulary

**use_case_tags (preferred):**
```
home_office, student, travel_light, video_editing, photo_editing,
gaming_aaa, gaming_casual, local_ai_models, coding_dev,
family_shared, content_creation, 3d_rendering, music_production
```

**persona_tags (preferred):**
```
power_user, budget_buyer, creator, gamer, ai_enthusiast,
mobile_pro, beginner_friendly, business_professional
```

Extend vocabulary only when clearly supported by product data.

### 9.7 Re-enrichment modifier (appended to user message)

```
Reviewer feedback: {feedback}
Required tags (include if supported by data): {required_tags}
Forbidden tags (must NOT appear): {forbidden_tags}
Focus area: {focus}

Apply this feedback without inventing data not present in the product input.
Maintain strict JSON output and the same schema.
```

### 9.8 Few-shot examples

**Example 1 — Budget student laptop**

Input:
```json
{
  "category_context": "laptops",
  "product": {
    "sku_id": "LP-001",
    "title": "Acer Aspire 3 15.6\" Laptop Intel Core i3",
    "brand": "Acer",
    "category": "laptops",
    "price": 349.99,
    "attributes": {
      "processor": "Intel Core i3-1215U",
      "ram_gb": 8,
      "storage_gb": 256,
      "display_inches": 15.6,
      "weight_kg": 1.9,
      "battery_hours": 8
    }
  }
}
```

Output:
```json
{
  "use_case_tags": ["student", "home_office", "family_shared"],
  "persona_tags": ["budget_buyer", "beginner_friendly"],
  "trust_signals": { "warranty_months": null, "certifications": [], "sustainability_notes": "" },
  "agent_summary": "Affordable 15.6\" laptop for everyday tasks and light productivity. Ideal for students and home users on a budget.",
  "confidence_score": 0.82,
  "evidence_fields": ["price", "processor", "ram_gb", "battery_hours"],
  "suggested_attributes": [
    {"key": "gpu", "value": null, "source": "missing", "reason": "Integrated vs dedicated graphics decides gaming and editing fit."},
    {"key": "operating_system", "value": null, "source": "missing", "reason": "Shoppers filter laptops by Windows, ChromeOS or no OS."},
    {"key": "display_resolution", "value": null, "source": "missing", "reason": "Resolution affects text sharpness on a 15.6\" screen."}
  ]
}
```

**Example 2 — High-end AI workstation**

Input:
```json
{
  "category_context": "laptops",
  "product": {
    "sku_id": "LP-002",
    "title": "ASUS ProArt Studiobook 16 OLED Creator Laptop",
    "brand": "ASUS",
    "category": "laptops",
    "price": 2499.00,
    "attributes": {
      "processor": "Intel Core Ultra 9 185H with NPU",
      "ram_gb": 64,
      "storage_gb": 2000,
      "gpu": "NVIDIA RTX 4070",
      "display_type": "OLED",
      "warranty": "2 years international"
    }
  }
}
```

Output:
```json
{
  "use_case_tags": ["video_editing", "photo_editing", "3d_rendering", "local_ai_models", "coding_dev"],
  "persona_tags": ["power_user", "creator", "ai_enthusiast"],
  "trust_signals": { "warranty_months": 24, "certifications": [], "sustainability_notes": "" },
  "agent_summary": "Professional OLED creator laptop with NPU and RTX 4070, built for video editing, 3D rendering, and local AI workloads.",
  "confidence_score": 0.94,
  "evidence_fields": ["processor", "ram_gb", "gpu", "display_type", "warranty"],
  "suggested_attributes": [
    {"key": "display_inches", "value": 16, "source": "product_text", "reason": "Title states a 16\" display."},
    {"key": "weight_kg", "value": null, "source": "missing", "reason": "Portability matters for creators working on location."},
    {"key": "battery_hours", "value": null, "source": "missing", "reason": "Battery life is a key comparison point for laptops."}
  ]
}
```

**Example 3 — Mid-range gaming laptop**

Input:
```json
{
  "category_context": "laptops",
  "product": {
    "sku_id": "LP-003",
    "title": "Lenovo IdeaPad Gaming 3 15.6\"",
    "brand": "Lenovo",
    "category": "laptops",
    "price": 799.00,
    "attributes": {
      "processor": "AMD Ryzen 5 7535HS",
      "ram_gb": 16,
      "gpu": "NVIDIA RTX 3050",
      "display_hz": 120,
      "weight_kg": 2.2
    }
  }
}
```

Output:
```json
{
  "use_case_tags": ["gaming_aaa", "gaming_casual", "coding_dev"],
  "persona_tags": ["gamer", "budget_buyer"],
  "trust_signals": { "warranty_months": null, "certifications": [], "sustainability_notes": "" },
  "agent_summary": "Mid-range gaming laptop with RTX 3050 and 120Hz display, capable of running modern AAA titles at medium settings.",
  "confidence_score": 0.88,
  "evidence_fields": ["gpu", "display_hz", "processor", "ram_gb"],
  "suggested_attributes": [
    {"key": "display_inches", "value": 15.6, "source": "product_text", "reason": "Title states a 15.6\" display."},
    {"key": "storage_gb", "value": null, "source": "missing", "reason": "Storage size limits how many games fit installed."},
    {"key": "battery_hours", "value": null, "source": "missing", "reason": "Gaming laptops vary widely in battery life."}
  ]
}
```

---

## 10. Review Workflow

### 10.1 Actions

| Action | Required fields | DB effect |
|---|---|---|
| `approve` | `version_id` | `review_state.status = APPROVED`, set `reviewer_id`, `reviewed_at` |
| `approve_with_edits` | `version_id`, `edited_enrichment` | New `enrichment_version` (generated_by=human, parent=current), that version → APPROVED |
| `reject` | `version_id`, `rejection_reason` | `review_state.status = REJECTED` |
| `escalate` | `version_id`, `escalate_to_user_id`, `escalate_reason` | `review_state.status = ESCALATED`, create `assignment` |
| `comment` | `version_id`, `comment_type`, `comment_body` | Insert `review_comment` — does NOT change `review_state` |
| `reenrich` | `version_id`, optional `reenrich_feedback` | Triggers `/enrich` internally → new version PENDING_REVIEW |

### 10.2 State transitions

```
LLM success  → PENDING_REVIEW → APPROVED
                              → APPROVED  (with new human version)
                              → REJECTED
                              → ESCALATED → PENDING_REVIEW (after reassignment)
                              → REENRICH  → PENDING_REVIEW (new LLM version)
LLM failure  → NEEDS_REVIEW   → REENRICH  → PENDING_REVIEW
```

---

## 11. Review UI Specification

### 11.1 Roles in UI

- **Admin:** full access, user management, batch operations, export, Algolia sync
- **Reviewer General:** all SKUs / all categories, no queue restriction
- **Reviewer Category:** auto-filtered queue for own category only; filter cannot be removed

### 11.2 Dashboard (`/dashboard`)

**Top widgets:**
- Backlog count cards: PENDING_REVIEW, ESCALATED (with trend indicator)
- Throughput sparkline: approved SKUs / last 7 days
- Top 5 rejection reasons: horizontal bar chart

**SKU table:**
- Columns: `sku_id`, `title`, `brand`, `category`, `priority`, `confidence_score`, `status`, `age`
- Sortable: `priority`, `confidence_score`, `age`
- Filters: category, status (multi-select), priority (multi-select), confidence_score range (slider), free-text search
- Keyboard: `j`/`k` navigate rows, `Enter` open SKU

### 11.3 Review Workspace (`/skus/[sku_id]`)

**4-panel layout:**

**Panel 1 — Product (read-only)**
Title, brand, category, price, key specs from `attributes`.

**Panel 2 — Audit**
`completeness_score` + `richness_score` as progress bars (green ≥ 0.8, yellow ≥ 0.6, red < 0.6). `missing_critical_fields` list.

**Panel 3 — Enrichment editor**
- `use_case_tags` / `persona_tags`: chip inputs (add on Enter/comma, remove on ×, silent dedup, max 10)
- `trust_signals`: `warranty_months` number input, `certifications` chip input, `sustainability_notes` textarea
- `agent_summary`: textarea with live counter (yellow at 200, red + blocked at 240)
- `confidence_score`: read-only badge (yellow < 0.7, green ≥ 0.7)
- `suggested_attributes`: list with key, source badge ("from text" / "missing"), editable value and reason; reviewer can remove a suggestion
- Dirty state: "Approve with edits" active only when changes exist

**Panel 4 — History + Comments (tabs)**
- History: version timeline (LLM/human icons), side-by-side diff of tags and summary
- Comments: thread with `comment_type` selector (NOTE / PROMPT_FEEDBACK / QUALITY_FLAG)

**Sticky action bar:**

| Button | Active when | Behavior |
|---|---|---|
| Approve | PENDING_REVIEW | Direct API call |
| Approve with edits | dirty = true | Sends edited payload |
| Reject | always | Modal: rejection reason required (min 10 chars) |
| Re-enrich | always | Modal: feedback, focus, required_tags, forbidden_tags |
| Escalate | always | Modal: user selector (from API), reason |
| Save draft | dirty = true | Saves to localStorage, no API call |

**Auto-save:** localStorage every 30s when dirty. Shows "Draft saved" toast.

**Keyboard shortcuts:**
- `a` → Approve
- `r` → open Reject modal
- `[` / `]` → previous / next SKU in filtered list

### 11.4 Admin Panel (`/admin`)
- User list + role assignment
- Category assignment per user
- Manual SKU reassignment
- Audit threshold configuration
- Prompt version metadata management

---

## 12. Export & Sync

**Export (`GET /exports/latest`):**
- Includes only the latest APPROVED version per SKU
- Also writes `catalog_agent_ready.json` to Cloud Storage (env: `EXPORT_BUCKET`)

**Export record schema:**
```json
{
  "sku_id": "string",
  "title": "string",
  "brand": "string",
  "category": "string",
  "price": 0.0,
  "use_case_tags": [],
  "persona_tags": [],
  "trust_signals": {},
  "agent_summary": "string",
  "confidence_score": 0.0,
  "version_id": "string",
  "approved_at": "timestamp"
}
```

**Algolia sync (`POST /algolia/sync`):**
- Partial update only — enrichment fields are written without overwriting other Algolia attributes
- `objectID` = `sku_id`
- Fields synced: `use_case_tags`, `persona_tags`, `trust_signals`, `agent_summary`, `confidence_score`
- Env vars: `ALGOLIA_APP_ID`, `ALGOLIA_API_KEY`, `ALGOLIA_INDEX_NAME`

---

## 13. Auth

**Development stub (Phase 1–7):**
```python
async def get_current_user(
    x_user_email: str = Header(..., alias="X-User-Email"),
    db: Session = Depends(get_db),
) -> User:
    # Dev: reads identity from X-User-Email header
    # Production: header is injected and signed by Cloud IAP
    # Replace body with IAP JWT validation in Phase 8
    ...
```

**Production (Phase 8):** Cloud IAP injects and signs the `X-Goog-Authenticated-User-Email` header. Never trust client-supplied identity headers in production without IAP validation.

---

## 14. Observability

**Structured logs** — every log line includes: `job_id`, `sku_id`, `version_id`

**Metrics:**
- Throughput: SKUs/min processed
- LLM failure rate: % calls resulting in NEEDS_REVIEW
- Latency: p95 per endpoint
- Queue backlog: open PENDING_REVIEW count
- Time-to-approval: median time from PENDING_REVIEW → APPROVED
- Human edit rate: % versions that went through approve_with_edits

**Audit trail:** who changed what and when, stored in `review_states` + `review_comments`.

---

## 15. KPIs

| KPI | Target |
|---|---|
| Attribute completeness | > 90% |
| NaN / empty field rate | < 5% |
| Review time per 100 SKUs | < 4 hours |
| Use case tags per SKU | ≥ 3 |
| LLM failure rate | < 5% |

---

## 16. Scalability

| Phase | SKU count |
|---|---|
| Phase 1 | 50 SKUs (dev/test) |
| Phase 2 | 1,000 SKUs |
| Phase 3 | 12,000 SKUs |

---

## 17. Security

- All enrichment versions immutable after creation (append-only)
- Full human change audit via `review_states` + `review_comments`
- Role-based access control enforced server-side on every endpoint
- JSON schema validation on all LLM output before persisting
- LLM fallback path (NEEDS_REVIEW) prevents silent data corruption
- Secrets in Secret Manager in production — never in env files
- Rate limiting on `/ingest/jobs` and `/skus/{sku_id}/enrich`
