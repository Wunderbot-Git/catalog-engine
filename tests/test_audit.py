import pytest

from api.models import AuditResult, Product, RoleEnum, SourceEnum, User, UserRole
from api.services.audit import compute_completeness_score, compute_priority, compute_richness_score
from tests.conftest import auth_headers


def _create_admin(db, email="admin@test.com"):
    user = User(name="Admin", email=email)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role=RoleEnum.ADMIN))
    db.flush()
    return user


def _create_reviewer(db, email="reviewer@test.com"):
    user = User(name="Reviewer", email=email)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role=RoleEnum.REVIEWER_GENERAL))
    db.flush()
    return user


def _create_product(
    db,
    sku_id="SKU-1",
    title="Test Product Title That Is Long Enough",
    brand="Some Brand",
    category="laptops",
    price=100.0,
    attributes=None,
):
    p = Product(
        sku_id=sku_id,
        title=title,
        brand=brand,
        category=category,
        price=price,
        source=SourceEnum.JSON,
        attributes_json=attributes
        if attributes is not None
        else {
            "processor": "i7",
            "ram_gb": 16,
            "storage_gb": 512,
            "display_inches": 15.6,
            "weight_kg": 1.8,
        },
    )
    db.add(p)
    db.flush()
    return p


# --- Unit tests for scoring functions ---


def test_completeness_score_all_fields_returns_1(db_session):
    p = _create_product(db_session)
    score, missing = compute_completeness_score(p)
    assert score == 1.0
    assert missing == []


def test_completeness_score_missing_title_reduces_score(db_session):
    p = _create_product(db_session, title="")
    score, missing = compute_completeness_score(p)
    assert score == pytest.approx(0.80, abs=0.01)
    assert "title" in missing


def test_completeness_score_empty_attributes_reduces_score(db_session):
    p = _create_product(db_session, attributes={})
    score, missing = compute_completeness_score(p)
    assert score == pytest.approx(0.65, abs=0.01)
    assert "attributes" in missing


def test_richness_score_long_title_adds_points(db_session):
    p = _create_product(db_session, title="A" * 30, brand="Single", attributes={"a": "b"})
    score, low = compute_richness_score(p)
    assert score >= 0.25  # at least title length points


def test_richness_score_few_attributes_is_low(db_session):
    p = _create_product(db_session, attributes={"a": "b"})
    score, low = compute_richness_score(p)
    assert "few_attributes" in low


def test_priority_high_when_completeness_below_0_6(db_session):
    assert compute_priority(0.5, 0.8) == "HIGH"


def test_priority_high_when_richness_below_0_5(db_session):
    assert compute_priority(0.9, 0.4) == "HIGH"


def test_priority_low_when_all_scores_good(db_session):
    assert compute_priority(0.9, 0.8) == "LOW"


# --- Integration tests for the endpoint ---


@pytest.mark.asyncio
async def test_audit_run_persists_to_audit_results(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)

    response = await client.post("/audit/run", json={}, headers=auth_headers(admin.email))
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1

    results = db_session.query(AuditResult).all()
    assert len(results) == 1
    assert results[0].sku_id == "SKU-1"


@pytest.mark.asyncio
async def test_audit_run_specific_sku_ids_only_audits_those(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, sku_id="SKU-1")
    _create_product(db_session, sku_id="SKU-2")

    response = await client.post(
        "/audit/run", json={"sku_ids": ["SKU-1"]}, headers=auth_headers(admin.email)
    )
    data = response.json()
    assert data["processed"] == 1

    results = db_session.query(AuditResult).all()
    assert len(results) == 1
    assert results[0].sku_id == "SKU-1"


@pytest.mark.asyncio
async def test_audit_run_requires_admin_role(client, db_session):
    reviewer = _create_reviewer(db_session)
    response = await client.post("/audit/run", json={}, headers=auth_headers(reviewer.email))
    assert response.status_code == 403
