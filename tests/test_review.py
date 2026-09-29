import pytest

from api.dependencies.llm import get_llm_client
from api.llm.base import LLMClient
from api.llm.types import EnrichmentResult, TrustSignals
from api.main import app
from api.models import (
    Assignment,
    EnrichmentVersion,
    GeneratedByEnum,
    Product,
    ReviewComment,
    ReviewState,
    ReviewStatusEnum,
    RoleEnum,
    SourceEnum,
    User,
    UserRole,
)
from tests.conftest import auth_headers

# --- Mock LLM ---


class MockLLMClient(LLMClient):
    def __init__(self):
        self.model_name = "mock"

    async def enrich(self, product, category_context):
        return EnrichmentResult(
            use_case_tags=["student"],
            persona_tags=["budget_buyer"],
            trust_signals=TrustSignals(),
            agent_summary="Re-enriched summary.",
            confidence_score=0.85,
            evidence_fields=["price"],
        )


# --- Helpers ---


def _create_user(db, email, role, category=None):
    user = User(name="Test", email=email)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role=role, category=category))
    db.flush()
    return user


def _create_product(db, sku_id="SKU-1", category="laptops"):
    p = Product(
        sku_id=sku_id,
        title="Test Product",
        brand="Brand",
        category=category,
        price=100.0,
        source=SourceEnum.JSON,
        attributes_json={"processor": "i5"},
    )
    db.add(p)
    db.flush()
    return p


def _create_enrichment(db, sku_id, status=ReviewStatusEnum.PENDING_REVIEW):
    v = EnrichmentVersion(
        sku_id=sku_id,
        generated_by=GeneratedByEnum.LLM,
        use_case_tags=["student"],
        persona_tags=["budget_buyer"],
        trust_signals={"warranty_months": None, "certifications": [], "sustainability_notes": ""},
        agent_summary="Original summary.",
        confidence_score=0.8,
        evidence_fields=["price"],
    )
    db.add(v)
    db.flush()
    rs = ReviewState(version_id=v.version_id, review_status=status)
    db.add(rs)
    db.flush()
    return v, rs


def _setup_llm_mock():
    mock = MockLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: mock
    return mock


def _cleanup_llm_mock():
    app.dependency_overrides.pop(get_llm_client, None)


def _review_payload(action, version_id, **kwargs):
    return {"action": action, "version_id": str(version_id), **kwargs}


# --- Tests ---


@pytest.mark.asyncio
async def test_approve_sets_status_approved(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    response = await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve", v.version_id),
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    rs = db_session.query(ReviewState).filter(ReviewState.version_id == v.version_id).first()
    assert rs.review_status == ReviewStatusEnum.APPROVED


@pytest.mark.asyncio
async def test_approve_sets_reviewer_id_and_reviewed_at(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve", v.version_id),
        headers=auth_headers(admin.email),
    )

    rs = db_session.query(ReviewState).filter(ReviewState.version_id == v.version_id).first()
    assert rs.reviewer_id == admin.id
    assert rs.reviewed_at is not None


@pytest.mark.asyncio
async def test_approve_with_edits_creates_new_human_version(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    edited = {
        "use_case_tags": ["gaming_casual"],
        "persona_tags": ["gamer"],
        "trust_signals": {"warranty_months": 12, "certifications": [], "sustainability_notes": ""},
        "agent_summary": "Edited summary.",
        "confidence_score": 0.9,
        "evidence_fields": ["gpu"],
    }
    response = await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve_with_edits", v.version_id, edited_enrichment=edited),
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    versions = db_session.query(EnrichmentVersion).filter(EnrichmentVersion.sku_id == "SKU-1").all()
    assert len(versions) == 2
    human_version = [vv for vv in versions if vv.generated_by == GeneratedByEnum.HUMAN][0]
    assert human_version.use_case_tags == ["gaming_casual"]
    assert human_version.suggested_attributes == []


@pytest.mark.asyncio
async def test_approve_with_edits_keeps_reviewed_suggested_attributes(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    edited = {
        "use_case_tags": ["student"],
        "persona_tags": ["budget_buyer"],
        "trust_signals": {"warranty_months": None, "certifications": []},
        "agent_summary": "Edited summary.",
        "confidence_score": 0.8,
        "suggested_attributes": [
            {"key": "Display Inches", "value": 14, "source": "product_text", "reason": "Title."},
        ],
    }
    response = await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve_with_edits", v.version_id, edited_enrichment=edited),
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    versions = await client.get("/skus/SKU-1/versions", headers=auth_headers(admin.email))
    latest = versions.json()[0]
    assert latest["generated_by"] == "human"
    assert latest["suggested_attributes"] == [
        {"key": "display_inches", "value": 14, "source": "product_text", "reason": "Title."}
    ]


@pytest.mark.asyncio
async def test_approve_with_edits_parent_is_llm_version(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    edited = {
        "use_case_tags": ["student"],
        "persona_tags": ["buyer"],
        "trust_signals": {
            "warranty_months": None,
            "certifications": [],
            "sustainability_notes": "",
        },
        "agent_summary": "Edit.",
        "confidence_score": 0.8,
        "evidence_fields": [],
    }
    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve_with_edits", v.version_id, edited_enrichment=edited),
        headers=auth_headers(admin.email),
    )

    human_v = (
        db_session.query(EnrichmentVersion)
        .filter(EnrichmentVersion.generated_by == GeneratedByEnum.HUMAN)
        .first()
    )
    assert human_v.parent_version_id == v.version_id


@pytest.mark.asyncio
async def test_approve_with_edits_new_version_is_approved(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    edited = {
        "use_case_tags": ["student"],
        "persona_tags": ["buyer"],
        "trust_signals": {
            "warranty_months": None,
            "certifications": [],
            "sustainability_notes": "",
        },
        "agent_summary": "Edit.",
        "confidence_score": 0.8,
        "evidence_fields": [],
    }
    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve_with_edits", v.version_id, edited_enrichment=edited),
        headers=auth_headers(admin.email),
    )

    human_v = (
        db_session.query(EnrichmentVersion)
        .filter(EnrichmentVersion.generated_by == GeneratedByEnum.HUMAN)
        .first()
    )
    rs = db_session.query(ReviewState).filter(ReviewState.version_id == human_v.version_id).first()
    assert rs.review_status == ReviewStatusEnum.APPROVED


@pytest.mark.asyncio
async def test_reject_requires_rejection_reason_422_if_missing(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    response = await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("reject", v.version_id),
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_sets_status_rejected(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("reject", v.version_id, rejection_reason="Tags are wrong"),
        headers=auth_headers(admin.email),
    )

    rs = db_session.query(ReviewState).filter(ReviewState.version_id == v.version_id).first()
    assert rs.review_status == ReviewStatusEnum.REJECTED


@pytest.mark.asyncio
async def test_escalate_creates_assignment_for_target_user(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    target = _create_user(db_session, "target@test.com", RoleEnum.REVIEWER_GENERAL)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload(
            "escalate",
            v.version_id,
            escalate_to_user_id=str(target.id),
            escalate_reason="Needs expert review",
        ),
        headers=auth_headers(admin.email),
    )

    assignment = db_session.query(Assignment).first()
    assert assignment is not None
    assert assignment.assigned_to_user_id == target.id
    assert assignment.sku_id == "SKU-1"


@pytest.mark.asyncio
async def test_escalate_sets_status_escalated(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    target = _create_user(db_session, "target@test.com", RoleEnum.REVIEWER_GENERAL)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload(
            "escalate",
            v.version_id,
            escalate_to_user_id=str(target.id),
            escalate_reason="Needs expert",
        ),
        headers=auth_headers(admin.email),
    )

    rs = db_session.query(ReviewState).filter(ReviewState.version_id == v.version_id).first()
    assert rs.review_status == ReviewStatusEnum.ESCALATED


@pytest.mark.asyncio
async def test_comment_does_not_change_review_status(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    await client.post(
        "/skus/SKU-1/review",
        json=_review_payload(
            "comment",
            v.version_id,
            comment_type="NOTE",
            comment_body="Looks good overall",
        ),
        headers=auth_headers(admin.email),
    )

    rs = db_session.query(ReviewState).filter(ReviewState.version_id == v.version_id).first()
    assert rs.review_status == ReviewStatusEnum.PENDING_REVIEW

    comment = db_session.query(ReviewComment).first()
    assert comment is not None
    assert comment.body == "Looks good overall"


@pytest.mark.asyncio
async def test_comment_requires_body(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")

    response = await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("comment", v.version_id, comment_type="NOTE"),
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reenrich_triggers_new_llm_version_pending(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1")
    _setup_llm_mock()

    try:
        await client.post(
            "/skus/SKU-1/review",
            json=_review_payload("reenrich", v.version_id, reenrich_feedback="Add gaming tags"),
            headers=auth_headers(admin.email),
        )

        versions = (
            db_session.query(EnrichmentVersion).filter(EnrichmentVersion.sku_id == "SKU-1").all()
        )
        assert len(versions) == 2

        new_v = [vv for vv in versions if vv.version_id != v.version_id][0]
        assert new_v.generated_by == GeneratedByEnum.LLM
        assert new_v.parent_version_id == v.version_id

        new_rs = (
            db_session.query(ReviewState).filter(ReviewState.version_id == new_v.version_id).first()
        )
        assert new_rs.review_status == ReviewStatusEnum.PENDING_REVIEW
    finally:
        _cleanup_llm_mock()


@pytest.mark.asyncio
async def test_reviewer_category_blocked_from_other_category(client, db_session):
    cat_reviewer = _create_user(
        db_session, "cat@test.com", RoleEnum.REVIEWER_CATEGORY, category="phones"
    )
    _create_product(db_session, category="laptops")
    v, _ = _create_enrichment(db_session, "SKU-1")

    response = await client.post(
        "/skus/SKU-1/review",
        json=_review_payload("approve", v.version_id),
        headers=auth_headers(cat_reviewer.email),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_review_returns_401_without_auth(client, db_session):
    response = await client.post(
        "/skus/SKU-1/review",
        json={"action": "approve", "version_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 401  # missing header


@pytest.mark.asyncio
async def test_versions_returns_ordered_history(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v1, _ = _create_enrichment(db_session, "SKU-1")
    v2, _ = _create_enrichment(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    response = await client.get("/skus/SKU-1/versions", headers=auth_headers(admin.email))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Ordered by created_at DESC — most recent first
    assert data[0]["version_id"] == str(v2.version_id)


@pytest.mark.asyncio
async def test_versions_includes_review_state_per_version(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    _create_product(db_session)
    v, _ = _create_enrichment(db_session, "SKU-1", ReviewStatusEnum.PENDING_REVIEW)

    response = await client.get("/skus/SKU-1/versions", headers=auth_headers(admin.email))
    data = response.json()
    assert data[0]["review_status"] == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_versions_404_for_unknown_sku(client, db_session):
    admin = _create_user(db_session, "admin@test.com", RoleEnum.ADMIN)
    response = await client.get("/skus/NONEXISTENT/versions", headers=auth_headers(admin.email))
    assert response.status_code == 404
