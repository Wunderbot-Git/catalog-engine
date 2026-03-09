import pytest

from api.models import Assignment, Product, RoleEnum, SourceEnum, User, UserRole
from tests.conftest import auth_headers


def _create_admin(db, email="admin@test.com"):
    user = User(name="Admin", email=email)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role=RoleEnum.ADMIN))
    db.flush()
    return user


def _create_user(db, email="user@test.com"):
    user = User(name="User", email=email)
    db.add(user)
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
        title="Test",
        brand="B",
        category="laptops",
        price=100.0,
        source=SourceEnum.JSON,
    )
    db.add(p)
    db.flush()
    return p


@pytest.mark.asyncio
async def test_list_users_returns_all_users(client, db_session):
    admin = _create_admin(db_session)
    _create_user(db_session, "other@test.com")

    response = await client.get("/admin/users", headers=auth_headers(admin.email))
    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_assign_role_creates_user_role(client, db_session):
    admin = _create_admin(db_session)
    user = _create_user(db_session)

    response = await client.post(
        f"/admin/users/{user.id}/roles",
        json={"role": "REVIEWER_GENERAL"},
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    roles = db_session.query(UserRole).filter(UserRole.user_id == user.id).all()
    assert any(r.role == RoleEnum.REVIEWER_GENERAL for r in roles)


@pytest.mark.asyncio
async def test_assign_reviewer_category_requires_category(client, db_session):
    admin = _create_admin(db_session)
    user = _create_user(db_session)

    response = await client.post(
        f"/admin/users/{user.id}/roles",
        json={"role": "REVIEWER_CATEGORY"},
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_remove_role_deletes_user_role(client, db_session):
    admin = _create_admin(db_session)
    user = _create_user(db_session)
    db_session.add(UserRole(user_id=user.id, role=RoleEnum.REVIEWER_GENERAL))
    db_session.flush()

    response = await client.request(
        "DELETE",
        f"/admin/users/{user.id}/roles",
        json={"role": "REVIEWER_GENERAL"},
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    roles = db_session.query(UserRole).filter(UserRole.user_id == user.id).all()
    assert len(roles) == 0


@pytest.mark.asyncio
async def test_reassign_sku_updates_assignment(client, db_session):
    admin = _create_admin(db_session)
    user = _create_user(db_session)
    _create_product(db_session)

    response = await client.put(
        "/admin/assignments/SKU-1",
        json={"assigned_to_user_id": str(user.id)},
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    assignment = db_session.query(Assignment).filter(Assignment.sku_id == "SKU-1").first()
    assert assignment.assigned_to_user_id == user.id


@pytest.mark.asyncio
async def test_update_thresholds_persists(client, db_session):
    admin = _create_admin(db_session)

    response = await client.put(
        "/admin/audit/thresholds",
        json={
            "completeness_high": 0.5,
            "completeness_medium": 0.7,
            "richness_high": 0.4,
            "richness_medium": 0.6,
        },
        headers=auth_headers(admin.email),
    )
    assert response.status_code == 200

    get_resp = await client.get("/admin/audit/thresholds", headers=auth_headers(admin.email))
    data = get_resp.json()
    assert data["completeness_high"] == 0.5


@pytest.mark.asyncio
async def test_all_admin_endpoints_require_admin_role(client, db_session):
    reviewer = _create_reviewer(db_session)
    headers = auth_headers(reviewer.email)

    r1 = await client.get("/admin/users", headers=headers)
    assert r1.status_code == 403

    r2 = await client.put("/admin/audit/thresholds", json={}, headers=headers)
    assert r2.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_gets_403(client, db_session):
    user = _create_user(db_session)
    # User has no roles at all
    response = await client.get("/admin/users", headers=auth_headers(user.email))
    assert response.status_code == 403
