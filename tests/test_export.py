from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from api.dependencies.storage import StorageClient, get_storage_client
from api.main import app
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


def _create_product(db, sku_id="SKU-1"):
    p = Product(
        sku_id=sku_id,
        title="Test Product",
        brand="Brand",
        category="laptops",
        price=100.0,
        source=SourceEnum.JSON,
    )
    db.add(p)
    db.flush()
    return p


def _create_version(db, sku_id, status, reviewed_at=None):
    v = EnrichmentVersion(
        sku_id=sku_id,
        generated_by=GeneratedByEnum.LLM,
        use_case_tags=["student"],
        persona_tags=["budget_buyer"],
        trust_signals={"warranty_months": None, "certifications": [], "sustainability_notes": ""},
        agent_summary="Test summary.",
        confidence_score=0.85,
        evidence_fields=["price"],
    )
    db.add(v)
    db.flush()
    rs = ReviewState(
        version_id=v.version_id,
        review_status=status,
        reviewed_at=reviewed_at
        or (datetime.now(timezone.utc) if status == ReviewStatusEnum.APPROVED else None),
    )
    db.add(rs)
    db.flush()
    return v


@pytest.mark.asyncio
async def test_export_returns_only_approved_versions(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_product(db_session, "SKU-2")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)
    _create_version(db_session, "SKU-2", ReviewStatusEnum.PENDING_REVIEW)

    response = await client.get("/exports/latest", headers=auth_headers(admin.email))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["sku_id"] == "SKU-1"


@pytest.mark.asyncio
async def test_export_returns_latest_approved_not_all_approved(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    import time

    time.sleep(0.01)  # ensure different created_at
    v2 = _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    response = await client.get("/exports/latest", headers=auth_headers(admin.email))
    data = response.json()
    assert len(data) == 1
    assert data[0]["version_id"] == str(v2.version_id)


@pytest.mark.asyncio
async def test_export_excludes_pending_rejected_escalated(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-P")
    _create_product(db_session, "SKU-R")
    _create_product(db_session, "SKU-E")
    _create_version(db_session, "SKU-P", ReviewStatusEnum.PENDING_REVIEW)
    _create_version(db_session, "SKU-R", ReviewStatusEnum.REJECTED)
    _create_version(db_session, "SKU-E", ReviewStatusEnum.ESCALATED)

    response = await client.get("/exports/latest", headers=auth_headers(admin.email))
    assert response.json() == []


@pytest.mark.asyncio
async def test_export_schema_has_all_required_fields(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    response = await client.get("/exports/latest", headers=auth_headers(admin.email))
    record = response.json()[0]
    required = {
        "sku_id",
        "title",
        "brand",
        "category",
        "price",
        "use_case_tags",
        "persona_tags",
        "trust_signals",
        "agent_summary",
        "confidence_score",
        "version_id",
        "approved_at",
    }
    assert required.issubset(set(record.keys()))


@pytest.mark.asyncio
async def test_export_requires_admin_role(client, db_session):
    reviewer = _create_reviewer(db_session)
    response = await client.get("/exports/latest", headers=auth_headers(reviewer.email))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_export_writes_to_cloud_storage_bucket(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    mock_storage = MagicMock(spec=StorageClient)
    app.dependency_overrides[get_storage_client] = lambda: mock_storage
    try:
        response = await client.get("/exports/latest", headers=auth_headers(admin.email))
        assert response.status_code == 200
        mock_storage.write_json.assert_called_once()
        path, data = mock_storage.write_json.call_args[0]
        assert path == "catalog_agent_ready.json"
        assert len(data) == 1
        assert data[0]["sku_id"] == "SKU-1"
    finally:
        app.dependency_overrides.pop(get_storage_client, None)


@pytest.mark.asyncio
async def test_storage_client_is_injectable_and_mockable(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session)
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)

    mock_storage = MagicMock(spec=StorageClient)
    app.dependency_overrides[get_storage_client] = lambda: mock_storage
    try:
        response = await client.get("/exports/latest", headers=auth_headers(admin.email))
        assert response.status_code == 200
        mock_storage.write_json.assert_called_once_with("catalog_agent_ready.json", response.json())
    finally:
        app.dependency_overrides.pop(get_storage_client, None)
