from datetime import datetime, timezone

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


def _create_user(db, email="admin@test.com", role=RoleEnum.ADMIN):
    user = User(name="Test", email=email)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role=role))
    db.flush()
    return user


def _create_product(db, sku_id="SKU-1"):
    p = Product(
        sku_id=sku_id,
        title="Test",
        brand="B",
        category="laptops",
        price=100.0,
        source=SourceEnum.JSON,
    )
    db.add(p)
    db.flush()
    return p


def _create_version(db, sku_id, status, rejection_reason=None):
    v = EnrichmentVersion(
        sku_id=sku_id,
        generated_by=GeneratedByEnum.LLM,
        use_case_tags=["student"],
        persona_tags=["buyer"],
        agent_summary="Summary.",
        confidence_score=0.8,
    )
    db.add(v)
    db.flush()
    rs = ReviewState(
        version_id=v.version_id,
        review_status=status,
        rejection_reason=rejection_reason,
        reviewed_at=datetime.now(timezone.utc)
        if status in (ReviewStatusEnum.APPROVED, ReviewStatusEnum.REJECTED)
        else None,
    )
    db.add(rs)
    db.flush()
    return v


@pytest.mark.asyncio
async def test_dashboard_stats_returns_backlog_counts(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1")
    _create_product(db_session, "SKU-2")
    _create_product(db_session, "SKU-3")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.PENDING_REVIEW)
    _create_version(db_session, "SKU-2", ReviewStatusEnum.PENDING_REVIEW)
    _create_version(db_session, "SKU-3", ReviewStatusEnum.ESCALATED)

    response = await client.get("/dashboard/stats", headers=auth_headers(user.email))
    assert response.status_code == 200
    data = response.json()
    assert data["pending_review_count"] == 2
    assert data["escalated_count"] == 1


@pytest.mark.asyncio
async def test_dashboard_stats_returns_throughput(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    response = await client.get("/dashboard/stats", headers=auth_headers(user.email))
    data = response.json()
    assert len(data["throughput"]) >= 1
    assert data["throughput"][0]["count"] >= 1


@pytest.mark.asyncio
async def test_dashboard_stats_returns_rejection_reasons(client, db_session):
    user = _create_user(db_session)
    _create_product(db_session, "SKU-1")
    _create_product(db_session, "SKU-2")
    _create_version(
        db_session, "SKU-1", ReviewStatusEnum.REJECTED, rejection_reason="Tags are wrong"
    )
    _create_version(
        db_session, "SKU-2", ReviewStatusEnum.REJECTED, rejection_reason="Tags are wrong"
    )

    response = await client.get("/dashboard/stats", headers=auth_headers(user.email))
    data = response.json()
    assert len(data["top_rejection_reasons"]) == 1
    assert data["top_rejection_reasons"][0]["reason"] == "Tags are wrong"
    assert data["top_rejection_reasons"][0]["count"] == 2


@pytest.mark.asyncio
async def test_dashboard_stats_requires_auth(client, db_session):
    response = await client.get("/dashboard/stats")
    assert response.status_code == 401
