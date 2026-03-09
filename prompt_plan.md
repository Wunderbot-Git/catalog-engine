# prompt_plan.md

## Catalog Intelligence Engine — Implementation Prompts

**Stack:**
- Backend: Python + FastAPI
- DB: PostgreSQL (Cloud SQL)
- ORM: SQLAlchemy + Alembic
- Validation: Pydantic v2 (use `@field_validator`, `@model_validator`, `model_config`)
- Workers: Cloud Run Jobs + Cloud Tasks
- Frontend: Next.js (App Router, TypeScript, Tailwind CSS)
- LLM: Vertex AI (Gemini) via injectable `GeminiClient`
- Search: Algolia
- Auth: Google Cloud IAP (stub in Prompt 3, full integration in Phase 8)

> These prompts are for a code-generation LLM implementing the system incrementally with TDD.
> **Every prompt must produce working tests before moving to the next.**
> Full system specification is in `specs.md` — reference it for all schema, API, and business rule details.

---

## Prompt 1 — Bootstrap Repository

Create a monorepo with the following structure:

```
repo/
  api/
  worker/
  ui/
  infra/
  tests/
```

**Requirements:**
- `api/requirements.txt`: `fastapi`, `uvicorn`, `sqlalchemy`, `psycopg2-binary`, `alembic`, `pydantic`, `pytest`, `httpx`
- `api/Dockerfile`
- `docker-compose.yml` with Postgres service (credentials from env vars only)
- `GET /health` → `{ "status": "ok" }`
- `.env.example` documenting all required env vars

**Test infrastructure (`tests/conftest.py`):**
- Create `conftest.py` with shared fixtures for all backend tests
- `db_session` fixture: creates a test database (use a separate test Postgres DB via `DATABASE_URL_TEST` env var, or override `DATABASE_URL` in test config)
- `client` fixture: `httpx.AsyncClient` wrapping the FastAPI `TestClient` with DB session override
- `auth_headers(email)` helper: returns `{"X-User-Email": email}` for authenticated test requests
- Use transaction rollback per test for isolation (begin transaction → run test → rollback)

**Tests required (`tests/test_health.py`):**
```
test_health_returns_200
test_health_response_has_status_ok
test_health_content_type_is_json
```

---

## Prompt 2 — Database Schema

Implement all SQLAlchemy models and Alembic migrations.

**Alembic conventions (mandatory):**
- `alembic init alembic` inside `api/`
- `DATABASE_URL` read from env — never hardcoded
- Initial migration via `alembic revision --autogenerate -m "initial_schema"`
- All future schema changes = new revisions, never edit existing ones
- Migration files committed to version control
- `alembic upgrade head` must be idempotent and run in CI

**Tables:** `products`, `audit_results`, `enrichment_versions`, `review_states`, `review_comments`, `assignments`, `users`, `user_roles`

**Enums (Python/SQLAlchemy, not standalone DB tables):** `RoleEnum` (ADMIN, REVIEWER_GENERAL, REVIEWER_CATEGORY), `SourceEnum`, `PriorityEnum`, `ReviewStatusEnum`, `GeneratedByEnum`, `AssignmentStatusEnum`

Full column specs and constraints: see `specs.md` section 5.

**Key constraints to implement:**
- `enrichment_versions.version_id`: UUID PK
- `enrichment_versions.parent_version_id`: nullable FK to self
- `review_states.version_id`: UNIQUE
- `user_roles`: composite PK `(user_id, role)`, `category` NOT NULL when role = REVIEWER_CATEGORY

**Indexes:** see `specs.md` section 5.8.

**Seed data (dev only — guarded by `ENV=development`):**
- 1 Admin, 1 Reviewer General, 1 Reviewer Category (category="laptops")
- 2 example SKUs in "laptops"

**Tests required (`tests/test_models.py`):**
```
test_all_tables_exist_after_migration
test_products_table_has_required_columns
test_enrichment_version_has_uuid_pk
test_review_states_version_id_is_unique
test_user_roles_category_required_for_reviewer_category
test_seed_data_present_in_dev_env
test_alembic_upgrade_is_idempotent
```

---

## Prompt 3 — SKU API + Auth Stub

Implement SKU read endpoints and the `current_user` dependency used by all protected endpoints.

**Auth stub — implement now, before any review/enrichment logic:**

```python
# api/dependencies/auth.py
async def get_current_user(
    x_user_email: str = Header(..., alias="X-User-Email"),
    db: Session = Depends(get_db),
) -> User:
    """
    Dev stub: identity from X-User-Email header.
    Production: Cloud IAP injects and signs this header.
    Replace body with IAP JWT validation in Phase 8.
    Never trust client-supplied header values without IAP in production.
    """
    user = db.query(User).filter(User.email == x_user_email, User.active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user
```

Also implement a `require_role(*roles)` FastAPI dependency for role enforcement.

**Endpoints:**

`GET /skus`
- Params: `category`, `status`, `priority`, `search`, `page` (default 1), `page_size` (default 20, max 100)
- Returns: `{ "items": [...], "total": int, "page": int, "page_size": int }`
- Protected: any authenticated user

`GET /skus/{sku_id}`
- Returns: product + latest enrichment version + latest audit result
- 404 if not found
- Protected: any authenticated user

**Tests required (`tests/test_skus.py`):**
```
test_get_skus_returns_paginated_list
test_get_skus_filter_by_category
test_get_skus_filter_by_status
test_get_skus_search_by_title
test_get_skus_search_by_sku_id
test_get_sku_by_id_returns_product_with_enrichment
test_get_sku_by_id_returns_404_for_unknown_sku
test_get_skus_returns_401_without_auth_header
test_page_size_capped_at_100
```

---

## Prompt 4 — Catalog Ingestion

**Pydantic input schema (field names must match canonical model in `specs.md` section 4):**

```python
class ProductIngestionItem(BaseModel):
    sku_id: str
    title: str
    brand: str = ""
    category: str
    price: float
    attributes: Dict[str, Any] = {}
    source: Literal["json", "csv", "excel", "algolia"]
    source_snapshot: Dict[str, Any] = {}

    @field_validator("sku_id")
    @classmethod
    def sku_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("sku_id must not be empty")
        return v.strip()

    @field_validator("price")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("price must be >= 0")
        return v

class IngestionJobRequest(BaseModel):
    items: List[ProductIngestionItem]

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: List[ProductIngestionItem]) -> List[ProductIngestionItem]:
        if not v:
            raise ValueError("items list must not be empty")
        return v
```

**Endpoint `POST /ingest/jobs`:**
- Upserts via `INSERT ... ON CONFLICT (sku_id) DO UPDATE`
- Single item failure must NOT rollback the batch
- Protected: ADMIN only
- Returns: `{ "count_ok": int, "count_failed": int, "errors": [{ "sku_id": "...", "reason": "..." }] }`

**Tests required (`tests/test_ingestion.py`):**
```
test_ingest_valid_items_returns_count_ok
test_ingest_upserts_existing_sku_no_duplicate
test_ingest_rejects_negative_price
test_ingest_rejects_empty_sku_id
test_ingest_rejects_missing_required_fields
test_ingest_empty_list_returns_400
test_ingest_mixed_valid_invalid_returns_partial_result
test_single_failure_does_not_rollback_batch
test_ingest_requires_admin_role
```

---

## Prompt 5 — Attribute Audit Engine

Implement scoring logic per `specs.md` section 8.

**Scoring rules summary:**
- `completeness_score`: weighted field presence (title 0.20, brand 0.15, category 0.15, price 0.15, attributes 0.35)
- `richness_score`: semantic quality (title length, attributes count, numeric values, brand word count — 0.25 each)
- `priority_for_enrichment`: HIGH if completeness < 0.6 OR richness < 0.5; MEDIUM if < 0.8 / < 0.7; LOW otherwise

**Endpoint `POST /audit/run`:**
- Optional body `{ "sku_ids": [] }` — if empty, runs on all products
- Upserts into `audit_results`
- Protected: ADMIN only
- Returns: `{ "processed": int, "high": int, "medium": int, "low": int }`

**Tests required (`tests/test_audit.py`):**
```
test_completeness_score_all_fields_returns_1
test_completeness_score_missing_title_reduces_score
test_completeness_score_empty_attributes_reduces_score
test_richness_score_long_title_adds_points
test_richness_score_few_attributes_is_low
test_priority_high_when_completeness_below_0_6
test_priority_high_when_richness_below_0_5
test_priority_low_when_all_scores_good
test_audit_run_persists_to_audit_results
test_audit_run_specific_sku_ids_only_audits_those
test_audit_run_requires_admin_role
```

---

## Prompt 6 — LLM Enrichment

Implement per `specs.md` sections 9.1–9.4.

**Context types (derived from few-shot examples in `specs.md` section 9.8):**

```python
# api/llm/types.py
class ProductContext(BaseModel):
    """Product data passed to the LLM for enrichment."""
    sku_id: str
    title: str
    brand: str = ""
    category: str
    price: float
    attributes: Dict[str, Any] = {}

class CategoryContext(BaseModel):
    """Category-level context for LLM enrichment."""
    category: str
    preferred_use_case_tags: List[str] = []
    preferred_persona_tags: List[str] = []
```

**LLMClient interface (implement exactly this):**

```python
# api/llm/base.py
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

**GeminiClient:**

```python
# api/llm/gemini_client.py
class GeminiClient(LLMClient):
    MAX_RETRIES = 3
    BACKOFF_SECONDS = [1, 2, 4]
    TIMEOUT_SECONDS = 30
    # System prompt and few-shot examples loaded from specs.md section 9.5/9.8 at startup
```

**EnrichmentResult schema:**

```python
class TrustSignals(BaseModel):
    warranty_months: Optional[int] = None
    certifications: List[str] = []
    sustainability_notes: str = ""

class EnrichmentResult(BaseModel):
    use_case_tags: List[str]
    persona_tags: List[str]
    trust_signals: TrustSignals
    agent_summary: str
    confidence_score: float
    evidence_fields: List[str] = []

    @field_validator("use_case_tags", "persona_tags")
    @classmethod
    def dedupe_and_slugify(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(tag.lower().replace(" ", "_") for tag in v))

    @field_validator("agent_summary")
    @classmethod
    def summary_max_240(cls, v: str) -> str:
        if len(v) > 240:
            raise ValueError("agent_summary max 240 chars")
        return v

    @field_validator("confidence_score")
    @classmethod
    def score_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence_score must be 0.0–1.0")
        return v
```

**Error handling (mandatory — full table in `specs.md` section 9.4):**
- Timeout → retry 3× with backoff → `NEEDS_REVIEW` on exhaustion
- Invalid JSON → `NEEDS_REVIEW`
- Schema failure → `NEEDS_REVIEW`
- `confidence_score < 0.7` → `priority_for_review = HIGH`

**Endpoint `POST /skus/{sku_id}/enrich`:**
- Protected: ADMIN or REVIEWER_GENERAL
- Optional body: `{ "feedback": "", "required_tags": [], "forbidden_tags": [], "focus": "" }`
- Creates `enrichment_version` (generated_by=llm)
- Re-enrichment: sets `parent_version_id` to latest existing version
- Creates `review_state` (PENDING_REVIEW or NEEDS_REVIEW)
- Returns: `{ "version_id": "...", "review_status": "..." }`
- `GeminiClient` must be injectable as a dependency

**Tests required (`tests/test_enrichment.py`):**
```
test_enrich_creates_enrichment_version
test_enrich_creates_review_state_pending
test_enrich_deduplicates_tags
test_enrich_slugifies_tags_to_snake_case
test_enrich_summary_over_240_chars_raises_error
test_enrich_confidence_out_of_range_raises_error
test_enrich_timeout_retries_3_times_then_sets_needs_review
test_enrich_invalid_json_sets_needs_review
test_enrich_schema_failure_sets_needs_review
test_enrich_low_confidence_sets_priority_high
test_reenrich_sets_parent_version_id
test_llm_client_is_injectable_and_mockable
```

---

## Prompt 7 — Review Workflow

Implement per `specs.md` section 10.
Uses `get_current_user` and `require_role` from Prompt 3 — do not re-implement auth here.

**Request schema:**

```python
class ReviewAction(str, Enum):
    APPROVE = "approve"
    APPROVE_WITH_EDITS = "approve_with_edits"
    REJECT = "reject"
    ESCALATE = "escalate"
    COMMENT = "comment"
    REENRICH = "reenrich"

class ReviewRequest(BaseModel):
    action: ReviewAction
    version_id: UUID
    rejection_reason: Optional[str] = None
    edited_enrichment: Optional[EnrichmentResult] = None
    comment_type: Optional[Literal["NOTE", "PROMPT_FEEDBACK", "QUALITY_FLAG"]] = None
    comment_body: Optional[str] = None
    escalate_to_user_id: Optional[UUID] = None
    escalate_reason: Optional[str] = None
    reenrich_feedback: Optional[str] = None
```

**Endpoint `POST /skus/{sku_id}/review`:**
- ADMIN + REVIEWER_GENERAL: all actions, all categories
- REVIEWER_CATEGORY: all actions, own category only (enforce server-side)

Business rules per action: see `specs.md` section 10.1.

**Endpoint `GET /skus/{sku_id}/versions`:**
- Returns all `enrichment_versions` for the SKU, ordered by `created_at DESC`
- Each entry includes: `version_id`, `parent_version_id`, `generated_by`, `model_name`, `use_case_tags`, `persona_tags`, `trust_signals`, `agent_summary`, `confidence_score`, `evidence_fields`, `created_at`, plus the associated `review_state` (status, reviewer_id, reviewed_at)
- 404 if `sku_id` not found
- Protected: any authenticated user

**Tests required (`tests/test_review.py`):**
```
test_approve_sets_status_approved
test_approve_sets_reviewer_id_and_reviewed_at
test_approve_with_edits_creates_new_human_version
test_approve_with_edits_parent_is_llm_version
test_approve_with_edits_new_version_is_approved
test_reject_requires_rejection_reason_422_if_missing
test_reject_sets_status_rejected
test_escalate_creates_assignment_for_target_user
test_escalate_sets_status_escalated
test_comment_does_not_change_review_status
test_comment_requires_body
test_reenrich_triggers_new_llm_version_pending
test_reviewer_category_blocked_from_other_category
test_review_returns_401_without_auth
test_versions_returns_ordered_history
test_versions_includes_review_state_per_version
test_versions_404_for_unknown_sku
```

---

## Prompt 8 — Export Catalog

**Endpoint `GET /exports/latest`:**
- Protected: ADMIN only
- Returns latest APPROVED version per SKU (SKUs with no approved version excluded)
- Writes `catalog_agent_ready.json` to Cloud Storage (env: `EXPORT_BUCKET`)
- Export schema: see `specs.md` section 12

**Tests required (`tests/test_export.py`):**
```
test_export_returns_only_approved_versions
test_export_returns_latest_approved_not_all_approved
test_export_excludes_pending_rejected_escalated
test_export_schema_has_all_required_fields
test_export_requires_admin_role
test_export_writes_to_cloud_storage_bucket
```

---

## Prompt 9 — Algolia Sync

**Endpoint `POST /algolia/sync`:**
- Protected: ADMIN only
- Reads latest APPROVED per SKU (same query as export)
- Partial update to Algolia — enrichment fields only, no overwrite of other attributes
- `objectID` = `sku_id`
- Fields: `use_case_tags`, `persona_tags`, `trust_signals`, `agent_summary`, `confidence_score`
- Env vars: `ALGOLIA_APP_ID`, `ALGOLIA_API_KEY`, `ALGOLIA_INDEX_NAME`
- Algolia client must be injectable for testing

**Tests required (`tests/test_algolia.py`):**
```
test_sync_sends_approved_skus
test_sync_uses_sku_id_as_object_id
test_sync_sends_only_enrichment_fields
test_sync_skips_non_approved_skus
test_sync_returns_count_synced
test_sync_requires_admin_role
test_algolia_client_is_injectable_and_mockable
```

---

## Prompt 10a — Frontend: Dashboard

> Full spec: `specs.md` section 11.2

**Stack:** Next.js App Router, TypeScript, Tailwind CSS.
**Auth:** `X-User-Email` header. Local dev: `DEV_USER_EMAIL` env var.

**Also implement** `GET /dashboard/stats` endpoint returning backlog counts, 7-day throughput, and top 5 rejection reasons.

**Page `/dashboard`:**

Top widgets (from `/dashboard/stats`):
- PENDING_REVIEW + ESCALATED count cards with trend indicator
- Approved SKUs / last 7 days sparkline
- Top 5 rejection reasons horizontal bar chart

SKU table:
- Columns: `sku_id`, `title`, `brand`, `category`, `priority`, `confidence_score`, `status`, `age`
- Sortable: `priority`, `confidence_score`, `age`
- Filters: category dropdown, status multi-select, priority multi-select, confidence_score range slider, free-text search
- REVIEWER_CATEGORY: category filter locked to own category (enforced in frontend + API)
- Row action: "Open" → `/skus/[sku_id]`
- Keyboard: `j`/`k` move row focus, `Enter` open

**Tests (`tests/ui/dashboard.test.tsx` — React Testing Library):**
```
test_renders_backlog_count_cards
test_renders_sku_table_with_rows
test_filter_by_category_updates_api_call
test_category_reviewer_category_filter_is_locked
test_keyboard_j_moves_focus_down
test_keyboard_enter_navigates_to_sku
```

---

## Prompt 10b — Frontend: Review Workspace

> Full spec: `specs.md` sections 11.3 and 10

**Page `/skus/[sku_id]`:**

**Panel 1 — Product (read-only):** title, brand, category, price, key specs.

**Panel 2 — Audit:** `completeness_score` + `richness_score` progress bars (green/yellow/red thresholds), `missing_critical_fields` list.

**Panel 3 — Enrichment editor:**
- `use_case_tags` / `persona_tags`: chip inputs (add on Enter/comma, remove on ×, silent dedup, max 10)
- `trust_signals`: warranty_months number input, certifications chip input, sustainability_notes textarea
- `agent_summary`: textarea, live counter (yellow at 200, red + disabled at 240)
- `confidence_score`: read-only badge (green ≥ 0.7, yellow < 0.7)
- Dirty state: "Approve with edits" active only when changes exist

**Panel 4 — History + Comments (tabs):**
- History: version timeline (LLM/human icons) + side-by-side diff
- Comments: thread with comment_type selector

**Sticky action bar** (full spec: `specs.md` section 11.3):
Approve | Approve with edits | Reject (modal, reason required min 10 chars) | Re-enrich (modal) | Escalate (modal) | Save draft (localStorage)

Auto-save to localStorage every 30s. "Draft saved" toast on save.
Keyboard: `a` approve, `r` reject modal, `[`/`]` prev/next SKU.

**Tests (`tests/ui/review_workspace.test.tsx`):**
```
test_renders_product_panel
test_renders_audit_score_bars_with_correct_colors
test_chip_input_adds_tag_on_enter
test_chip_input_deduplicates_silently
test_chip_input_removes_tag_on_x
test_approve_button_calls_api
test_approve_with_edits_inactive_when_clean
test_approve_with_edits_active_when_dirty
test_reject_modal_requires_reason_min_10_chars
test_reenrich_modal_sends_feedback_and_tags
test_summary_counter_warning_at_200
test_summary_counter_blocks_at_240
test_history_tab_shows_version_timeline
test_autosave_to_localstorage_on_interval
test_keyboard_a_triggers_approve
test_keyboard_brackets_navigate_between_skus
```

---

## Prompt 10c — Frontend: Admin Panel

> Full spec: `specs.md` section 11.4

**Stack:** Next.js App Router, TypeScript, Tailwind CSS.
**Auth:** ADMIN role required for all pages in this section.

**Also implement** admin-specific API endpoints:

```
GET    /admin/users                    — list all users with roles
POST   /admin/users/{user_id}/roles    — assign role (body: { role, category? })
DELETE /admin/users/{user_id}/roles    — remove role (body: { role })
PUT    /admin/assignments/{sku_id}     — reassign SKU to user
PUT    /admin/audit/thresholds         — update audit scoring thresholds
```

**Page `/admin`:**

User management:
- User list table: `name`, `email`, `active`, `roles` (comma-separated), `category`
- Inline role assignment: dropdown with ADMIN / REVIEWER_GENERAL / REVIEWER_CATEGORY
- When REVIEWER_CATEGORY selected: category input required (validated against known categories)
- Activate / deactivate user toggle

SKU management:
- SKU reassignment: search SKU, select target user from dropdown
- Shows current assignment status

Audit configuration:
- Editable threshold fields: completeness HIGH/MEDIUM cutoffs, richness HIGH/MEDIUM cutoffs
- Save button with confirmation modal
- Display current thresholds on load

**Tests (`tests/ui/admin.test.tsx` — React Testing Library):**
```
test_renders_user_list_table
test_assign_role_calls_api
test_category_required_for_reviewer_category
test_deactivate_user_toggle
test_sku_reassignment_calls_api
test_threshold_save_requires_confirmation
test_admin_page_requires_admin_role
```

**Tests (`tests/test_admin_api.py`):**
```
test_list_users_returns_all_users
test_assign_role_creates_user_role
test_assign_reviewer_category_requires_category
test_remove_role_deletes_user_role
test_reassign_sku_updates_assignment
test_update_thresholds_persists
test_all_admin_endpoints_require_admin_role
test_non_admin_gets_403
```

---

## Execution Order

> **Important:** Execute prompts in **phase order**, not prompt number order.
> Prompts 8 and 9 are numbered lower than 10a–10c but belong to Phase 7 (Integrations),
> which comes after Phase 6 (Frontend). The correct execution sequence is:
>
> **1 → 2 → 3 → 4 → 5 → 6 → 7 → 10a → 10b → 10c → 8 → 9**
>
> Phase 6 (Frontend) depends on the review API from Phase 5.
> Phase 7 (Export/Algolia) is independent of the frontend and can run after Phase 6.

## Prompt → Phase Mapping

| Prompt | Phase | Exec Order | Description |
|---|---|---|---|
| 1 | Phase 1 | 1 | Bootstrap |
| 2 | Phase 2 | 2 | Data layer |
| 3 | Phase 3 | 3 | SKU API + auth stub |
| 4 | Phase 3 | 4 | Ingestion |
| 5 | Phase 4 | 5 | Audit engine |
| 6 | Phase 4 | 6 | LLM enrichment |
| 7 | Phase 5 | 7 | Review workflow |
| 10a | Phase 6 | 8 | Frontend: Dashboard |
| 10b | Phase 6 | 9 | Frontend: Review Workspace |
| 10c | Phase 6 | 10 | Frontend: Admin Panel |
| 8 | Phase 7 | 11 | Export |
| 9 | Phase 7 | 12 | Algolia sync |
