import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api.models  # noqa: F401 — ensure all models are registered on Base.metadata
from api.config import DATABASE_URL_TEST
from api.database import Base, get_db
from api.main import app

DATABASE_URL_TEST = (
    DATABASE_URL_TEST or "postgresql://catalog:catalog@localhost:5432/catalog_engine_test"
)
test_engine = create_engine(DATABASE_URL_TEST)

TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def db_session():
    """Create tables, yield a session inside a transaction, then rollback."""
    Base.metadata.create_all(bind=test_engine)
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestSessionLocal(bind=connection)

    yield session

    session.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client(db_session):
    """Async HTTP client with DB session override."""

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def auth_headers(email: str = "admin@test.com") -> dict[str, str]:
    """Return auth headers for test requests."""
    return {"X-User-Email": email}
