from datetime import datetime, timezone

import pytest

from api.dependencies.algolia import AlgoliaClient, get_algolia_client
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


class MockAlgoliaClient(AlgoliaClient):
    def __init__(self):
        self.synced_objects = []

    def partial_update_objects(self, objects):
        self.synced_objects = objects
        return len(objects)


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


def _create_version(db, sku_id, status):
    v = EnrichmentVersion(
        sku_id=sku_id,
        generated_by=GeneratedByEnum.LLM,
        use_case_tags=["student"],
        persona_tags=["budget_buyer"],
        trust_signals={"warranty_months": None, "certifications": [], "sustainability_notes": ""},
        agent_summary="Test summary.",
        confidence_score=0.85,
    )
    db.add(v)
    db.flush()
    rs = ReviewState(
        version_id=v.version_id,
        review_status=status,
        reviewed_at=datetime.now(timezone.utc) if status == ReviewStatusEnum.APPROVED else None,
    )
    db.add(rs)
    db.flush()
    return v


def _setup_mock_algolia():
    mock = MockAlgoliaClient()
    app.dependency_overrides[get_algolia_client] = lambda: mock
    return mock


def _cleanup_mock_algolia():
    app.dependency_overrides.pop(get_algolia_client, None)


@pytest.mark.asyncio
async def test_sync_sends_approved_skus(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)
    mock = _setup_mock_algolia()

    try:
        response = await client.post("/algolia/sync", headers=auth_headers(admin.email))
        assert response.status_code == 200
        assert len(mock.synced_objects) == 1
    finally:
        _cleanup_mock_algolia()


@pytest.mark.asyncio
async def test_sync_uses_sku_id_as_object_id(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)
    mock = _setup_mock_algolia()

    try:
        await client.post("/algolia/sync", headers=auth_headers(admin.email))
        assert mock.synced_objects[0]["objectID"] == "SKU-1"
    finally:
        _cleanup_mock_algolia()


@pytest.mark.asyncio
async def test_sync_sends_only_enrichment_fields(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)
    mock = _setup_mock_algolia()

    try:
        await client.post("/algolia/sync", headers=auth_headers(admin.email))
        obj = mock.synced_objects[0]
        expected_keys = {
            "objectID",
            "use_case_tags",
            "persona_tags",
            "trust_signals",
            "agent_summary",
            "confidence_score",
        }
        assert set(obj.keys()) == expected_keys
    finally:
        _cleanup_mock_algolia()


@pytest.mark.asyncio
async def test_sync_skips_non_approved_skus(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.PENDING_REVIEW)
    mock = _setup_mock_algolia()

    try:
        response = await client.post("/algolia/sync", headers=auth_headers(admin.email))
        assert response.json()["count_synced"] == 0
        assert mock.synced_objects == []
    finally:
        _cleanup_mock_algolia()


@pytest.mark.asyncio
async def test_sync_returns_count_synced(client, db_session):
    admin = _create_admin(db_session)
    _create_product(db_session, "SKU-1")
    _create_product(db_session, "SKU-2")
    _create_version(db_session, "SKU-1", ReviewStatusEnum.APPROVED)
    _create_version(db_session, "SKU-2", ReviewStatusEnum.APPROVED)
    _setup_mock_algolia()

    try:
        response = await client.post("/algolia/sync", headers=auth_headers(admin.email))
        assert response.json()["count_synced"] == 2
    finally:
        _cleanup_mock_algolia()


@pytest.mark.asyncio
async def test_sync_requires_admin_role(client, db_session):
    reviewer = _create_reviewer(db_session)
    _setup_mock_algolia()

    try:
        response = await client.post("/algolia/sync", headers=auth_headers(reviewer.email))
        assert response.status_code == 403
    finally:
        _cleanup_mock_algolia()


def test_algolia_client_is_injectable_and_mockable():
    mock = MockAlgoliaClient()
    app.dependency_overrides[get_algolia_client] = lambda: mock
    try:
        assert isinstance(mock, AlgoliaClient)
    finally:
        app.dependency_overrides.pop(get_algolia_client, None)
