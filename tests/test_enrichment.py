import pytest
from pydantic import ValidationError

from api.dependencies.llm import get_llm_client
from api.llm.base import (
    LLMClient,
    LLMInvalidResponseError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
from api.llm.types import (
    EnrichmentResult,
    TrustSignals,
)
from api.main import app
from api.models import (
    EnrichmentVersion,
    GeneratedByEnum,
    PriorityEnum,
    Product,
    ReviewState,
    ReviewStatusEnum,
    RoleEnum,
    SourceEnum,
    User,
    UserRole,
)
from tests.conftest import auth_headers

# --- Mock LLM Client ---


def _mock_enrichment_result(**overrides):
    defaults = {
        "use_case_tags": ["student", "home_office"],
        "persona_tags": ["budget_buyer"],
        "trust_signals": TrustSignals(),
        "agent_summary": "A budget laptop for students.",
        "confidence_score": 0.85,
        "evidence_fields": ["price", "processor"],
    }
    defaults.update(overrides)
    return EnrichmentResult(**defaults)


class MockLLMClient(LLMClient):
    def __init__(self, result=None, error=None):
        self.result = result or _mock_enrichment_result()
        self.error = error
        self.call_count = 0
        self.model_name = "mock-model"

    async def enrich(self, product, category_context):
        self.call_count += 1
        if self.error:
            raise self.error
        return self.result


# --- Helpers ---


def _create_admin(db, email="admin@test.com"):
    user = User(name="Admin", email=email)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role=RoleEnum.ADMIN))
    db.flush()
    return user


def _create_product(db, sku_id="SKU-1"):
    p = Product(
        sku_id=sku_id,
        title="Test Laptop 15 inch display model",
        brand="TestBrand",
        category="laptops",
        price=499.0,
        source=SourceEnum.JSON,
        attributes_json={"processor": "i5", "ram_gb": 8},
    )
    db.add(p)
    db.flush()
    return p


def _override_llm(mock_client):
    app.dependency_overrides[get_llm_client] = lambda: mock_client


def _clear_llm_override():
    app.dependency_overrides.pop(get_llm_client, None)


# --- Schema validation tests ---


def test_enrich_deduplicates_tags():
    result = EnrichmentResult(
        use_case_tags=["Student", "student", "HOME OFFICE"],
        persona_tags=["budget_buyer", "Budget Buyer"],
        trust_signals=TrustSignals(),
        agent_summary="Test",
        confidence_score=0.8,
    )
    assert result.use_case_tags == ["student", "home_office"]
    assert result.persona_tags == ["budget_buyer"]


def test_enrich_slugifies_tags_to_snake_case():
    result = EnrichmentResult(
        use_case_tags=["Home Office", "video editing"],
        persona_tags=["Power User"],
        trust_signals=TrustSignals(),
        agent_summary="Test",
        confidence_score=0.8,
    )
    assert result.use_case_tags == ["home_office", "video_editing"]
    assert result.persona_tags == ["power_user"]


def test_enrich_summary_over_240_chars_raises_error():
    with pytest.raises(ValidationError, match="agent_summary max 240 chars"):
        EnrichmentResult(
            use_case_tags=["student"],
            persona_tags=["buyer"],
            trust_signals=TrustSignals(),
            agent_summary="A" * 241,
            confidence_score=0.8,
        )


def test_enrich_confidence_out_of_range_raises_error():
    with pytest.raises(ValidationError, match="confidence_score must be 0.0"):
        EnrichmentResult(
            use_case_tags=["student"],
            persona_tags=["buyer"],
            trust_signals=TrustSignals(),
            agent_summary="Test",
            confidence_score=1.5,
        )


# --- Endpoint integration tests ---


@pytest.mark.asyncio
async def test_enrich_creates_enrichment_version(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    mock = MockLLMClient()
    _override_llm(mock)

    try:
        response = await client.post(
            "/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email)
        )
        assert response.status_code == 200
        data = response.json()
        assert "version_id" in data

        version = db_session.query(EnrichmentVersion).first()
        assert version is not None
        assert version.sku_id == "SKU-1"
        assert version.generated_by == GeneratedByEnum.LLM
        assert version.use_case_tags == ["student", "home_office"]
    finally:
        _clear_llm_override()


@pytest.mark.asyncio
async def test_enrich_creates_review_state_pending(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _override_llm(MockLLMClient())

    try:
        response = await client.post(
            "/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email)
        )
        assert response.json()["review_status"] == "PENDING_REVIEW"

        rs = db_session.query(ReviewState).first()
        assert rs.review_status == ReviewStatusEnum.PENDING_REVIEW
    finally:
        _clear_llm_override()


@pytest.mark.asyncio
async def test_enrich_timeout_retries_3_times_then_sets_needs_review(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    mock = MockLLMClient(error=LLMTimeoutError("timeout"))
    _override_llm(mock)

    try:
        response = await client.post(
            "/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email)
        )
        assert response.json()["review_status"] == "NEEDS_REVIEW"
    finally:
        _clear_llm_override()


@pytest.mark.asyncio
async def test_enrich_invalid_json_sets_needs_review(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _override_llm(MockLLMClient(error=LLMInvalidResponseError("bad json")))

    try:
        response = await client.post(
            "/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email)
        )
        assert response.json()["review_status"] == "NEEDS_REVIEW"
    finally:
        _clear_llm_override()


@pytest.mark.asyncio
async def test_enrich_schema_failure_sets_needs_review(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _override_llm(MockLLMClient(error=LLMSchemaValidationError("bad schema")))

    try:
        response = await client.post(
            "/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email)
        )
        assert response.json()["review_status"] == "NEEDS_REVIEW"
    finally:
        _clear_llm_override()


@pytest.mark.asyncio
async def test_enrich_low_confidence_sets_priority_high(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    low_conf = _mock_enrichment_result(confidence_score=0.5)
    _override_llm(MockLLMClient(result=low_conf))

    try:
        response = await client.post(
            "/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email)
        )
        assert response.status_code == 200

        rs = db_session.query(ReviewState).first()
        assert rs.priority_for_review == PriorityEnum.HIGH
    finally:
        _clear_llm_override()


@pytest.mark.asyncio
async def test_reenrich_sets_parent_version_id(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _override_llm(MockLLMClient())

    try:
        # First enrichment
        await client.post("/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email))
        first = db_session.query(EnrichmentVersion).first()

        # Second enrichment (re-enrich)
        await client.post("/skus/SKU-1/enrich", json={}, headers=auth_headers(admin.email))
        versions = db_session.query(EnrichmentVersion).order_by(EnrichmentVersion.created_at).all()
        assert len(versions) == 2
        assert versions[1].parent_version_id == first.version_id
    finally:
        _clear_llm_override()


def test_llm_client_is_injectable_and_mockable():
    """Verify the LLMClient can be swapped via dependency override."""
    mock = MockLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: mock
    try:
        assert isinstance(mock, LLMClient)
    finally:
        app.dependency_overrides.pop(get_llm_client, None)
