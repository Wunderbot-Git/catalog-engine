"""Tests for IAP JWT authentication and dev-mode fallback."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import app
from api.models import RoleEnum, User, UserRole


@pytest.fixture
def seeded_user(db_session):
    """Create a test user in the DB."""
    user = User(name="Test User", email="test@example.com", active=True)
    db_session.add(user)
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role=RoleEnum.ADMIN))
    db_session.flush()
    return user


@pytest.mark.asyncio
async def test_dev_mode_x_user_email(client, seeded_user):
    """Without IAP_AUDIENCE, X-User-Email header is used (dev mode)."""
    resp = await client.get("/me", headers={"X-User-Email": "test@example.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_dev_mode_missing_header(client, seeded_user):
    """Without IAP_AUDIENCE and no X-User-Email header, returns 401."""
    resp = await client.get("/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dev_mode_unknown_user(client, seeded_user):
    """Unknown email returns 401."""
    resp = await client.get("/me", headers={"X-User-Email": "nobody@example.com"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_iap_mode_valid_jwt(db_session, seeded_user):
    """With IAP_AUDIENCE set, validates X-Goog-IAP-JWT-Assertion header."""
    from api.database import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with (
        patch("api.dependencies.auth.IAP_AUDIENCE", "/projects/123/apps/test"),
        patch("api.dependencies.auth._validate_iap_jwt", return_value="test@example.com"),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/me",
                headers={"X-Goog-IAP-JWT-Assertion": "fake.jwt.token"},
            )
            assert resp.status_code == 200
            assert resp.json()["email"] == "test@example.com"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_iap_mode_missing_jwt(db_session, seeded_user):
    """With IAP_AUDIENCE set but no JWT header, returns 401."""
    from api.database import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with patch("api.dependencies.auth.IAP_AUDIENCE", "/projects/123/apps/test"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get("/me")
            assert resp.status_code == 401

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_iap_mode_invalid_jwt(db_session, seeded_user):
    """With IAP_AUDIENCE set and invalid JWT, returns 401."""
    from fastapi import HTTPException

    from api.database import get_db

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    def _raise(*args, **kwargs):
        raise HTTPException(status_code=401, detail="Invalid IAP JWT")

    with (
        patch("api.dependencies.auth.IAP_AUDIENCE", "/projects/123/apps/test"),
        patch("api.dependencies.auth._validate_iap_jwt", side_effect=_raise),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.get(
                "/me",
                headers={"X-Goog-IAP-JWT-Assertion": "bad.jwt.token"},
            )
            assert resp.status_code == 401

    app.dependency_overrides.clear()
