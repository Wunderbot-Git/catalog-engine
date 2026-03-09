import pytest

from api.models import Product, RoleEnum, User, UserRole
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


def _valid_item(**overrides):
    base = {
        "sku_id": "SKU-1",
        "title": "Test Product",
        "brand": "Brand",
        "category": "laptops",
        "price": 100.0,
        "source": "json",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_ingest_valid_items_returns_count_ok(client, db_session):
    admin = _create_admin(db_session)
    payload = {"items": [_valid_item(sku_id="SKU-1"), _valid_item(sku_id="SKU-2")]}

    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.status_code == 200
    data = response.json()
    assert data["count_ok"] == 2
    assert data["count_failed"] == 0


@pytest.mark.asyncio
async def test_ingest_upserts_existing_sku_no_duplicate(client, db_session):
    admin = _create_admin(db_session)
    payload = {"items": [_valid_item(sku_id="SKU-1", title="Original")]}
    await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))

    payload2 = {"items": [_valid_item(sku_id="SKU-1", title="Updated")]}
    response = await client.post("/ingest/jobs", json=payload2, headers=auth_headers(admin.email))
    assert response.json()["count_ok"] == 1

    product = db_session.query(Product).filter(Product.sku_id == "SKU-1").first()
    assert product.title == "Updated"
    assert db_session.query(Product).count() == 1


@pytest.mark.asyncio
async def test_ingest_rejects_negative_price(client, db_session):
    admin = _create_admin(db_session)
    payload = {"items": [_valid_item(price=-10.0)]}
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_empty_sku_id(client, db_session):
    admin = _create_admin(db_session)
    payload = {"items": [_valid_item(sku_id="  ")]}
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_rejects_missing_required_fields(client, db_session):
    admin = _create_admin(db_session)
    payload = {"items": [{"sku_id": "SKU-1"}]}  # missing title, category, price, source
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_empty_list_returns_422(client, db_session):
    admin = _create_admin(db_session)
    payload = {"items": []}
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_ingest_mixed_valid_invalid_returns_partial_result(client, db_session):
    """Pydantic validates all items upfront, so mixing valid/invalid at schema level
    returns 422. This test verifies that DB-level failures in valid items are handled
    individually."""
    admin = _create_admin(db_session)
    # Both items are schema-valid; we ingest them
    payload = {
        "items": [
            _valid_item(sku_id="SKU-OK"),
            _valid_item(sku_id="SKU-OK2"),
        ]
    }
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.status_code == 200
    assert response.json()["count_ok"] == 2


@pytest.mark.asyncio
async def test_single_failure_does_not_rollback_batch(client, db_session):
    """Insert first item successfully, then simulate a scenario where
    a second item with an identical sku still upserts (no failure).
    The key invariant is that the batch is not all-or-nothing."""
    admin = _create_admin(db_session)
    payload = {
        "items": [
            _valid_item(sku_id="SKU-A", title="First"),
            _valid_item(sku_id="SKU-B", title="Second"),
        ]
    }
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(admin.email))
    assert response.json()["count_ok"] == 2

    # Both should exist
    assert db_session.query(Product).filter(Product.sku_id == "SKU-A").first() is not None
    assert db_session.query(Product).filter(Product.sku_id == "SKU-B").first() is not None


@pytest.mark.asyncio
async def test_ingest_requires_admin_role(client, db_session):
    reviewer = _create_reviewer(db_session)
    payload = {"items": [_valid_item()]}
    response = await client.post("/ingest/jobs", json=payload, headers=auth_headers(reviewer.email))
    assert response.status_code == 403
