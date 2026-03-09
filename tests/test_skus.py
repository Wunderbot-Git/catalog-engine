import pytest

from api.models import (
    EnrichmentVersion,
    GeneratedByEnum,
    Product,
    ReviewState,
    ReviewStatusEnum,
    RoleEnum,
    SourceEnum,
    User,
    UserRole,
)
from tests.conftest import auth_headers


def _create_user(db, email="user@test.com", role=RoleEnum.REVIEWER_GENERAL, category=None):
    user = User(name="Test User", email=email)
    db.add(user)
    db.flush()
    ur = UserRole(user_id=user.id, role=role, category=category)
    db.add(ur)
    db.flush()
    return user


def _create_product(db, sku_id="SKU-1", title="Test Product", category="laptops", price=100.0):
    p = Product(
        sku_id=sku_id,
        title=title,
        brand="Brand",
        category=category,
        price=price,
        source=SourceEnum.JSON,
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
        agent_summary="Test summary",
        confidence_score=0.8,
    )
    db.add(v)
    db.flush()
    rs = ReviewState(version_id=v.version_id, review_status=status)
    db.add(rs)
    db.flush()
    return v


@pytest.mark.asyncio
async def test_get_skus_returns_paginated_list(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1")
    _create_product(db_session, "SKU-2", title="Another Product")
    db_session.flush()

    response = await client.get("/skus", headers=auth_headers(user.email))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert len(data["items"]) == 2


@pytest.mark.asyncio
async def test_get_skus_filter_by_category(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1", category="laptops")
    _create_product(db_session, "SKU-2", category="phones")
    db_session.flush()

    response = await client.get("/skus?category=laptops", headers=auth_headers(user.email))
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["sku_id"] == "SKU-1"


@pytest.mark.asyncio
async def test_get_skus_filter_by_status(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1")
    _create_product(db_session, "SKU-2")
    _create_enrichment(db_session, "SKU-1", ReviewStatusEnum.APPROVED)
    _create_enrichment(db_session, "SKU-2", ReviewStatusEnum.PENDING_REVIEW)

    response = await client.get("/skus?status=APPROVED", headers=auth_headers(user.email))
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["sku_id"] == "SKU-1"


@pytest.mark.asyncio
async def test_get_skus_search_by_title(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1", title="Acer Aspire Laptop")
    _create_product(db_session, "SKU-2", title="Samsung Galaxy Phone")

    response = await client.get("/skus?search=aspire", headers=auth_headers(user.email))
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["sku_id"] == "SKU-1"


@pytest.mark.asyncio
async def test_get_skus_search_by_sku_id(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "LP-001", title="Laptop One")
    _create_product(db_session, "PH-001", title="Phone One")

    response = await client.get("/skus?search=LP-001", headers=auth_headers(user.email))
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["sku_id"] == "LP-001"


@pytest.mark.asyncio
async def test_get_sku_by_id_returns_product_with_enrichment(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1")
    _create_enrichment(db_session, "SKU-1", ReviewStatusEnum.PENDING_REVIEW)

    response = await client.get("/skus/SKU-1", headers=auth_headers(user.email))
    assert response.status_code == 200
    data = response.json()
    assert data["sku_id"] == "SKU-1"
    assert data["enrichment"] is not None
    assert data["enrichment"]["use_case_tags"] == ["student"]
    assert data["enrichment"]["review_status"] == "PENDING_REVIEW"


@pytest.mark.asyncio
async def test_get_sku_by_id_returns_404_for_unknown_sku(client, db_session):
    user = _create_user(db_session)
    response = await client.get("/skus/NONEXISTENT", headers=auth_headers(user.email))
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_skus_returns_401_without_auth_header(client, db_session):
    response = await client.get("/skus")
    assert response.status_code == 401  # missing auth header


@pytest.mark.asyncio
async def test_page_size_capped_at_100(client, db_session):
    user = _create_user(db_session)
    response = await client.get("/skus?page_size=200", headers=auth_headers(user.email))
    assert response.status_code == 422  # validation error, page_size > 100
