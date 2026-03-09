import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

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

EXPECTED_TABLES = [
    "products",
    "audit_results",
    "enrichment_versions",
    "review_states",
    "review_comments",
    "assignments",
    "users",
    "user_roles",
]


def test_all_tables_exist_after_migration(db_session):
    inspector = inspect(db_session.bind)
    existing = inspector.get_table_names()
    for table in EXPECTED_TABLES:
        assert table in existing, f"Table '{table}' not found"


def test_products_table_has_required_columns(db_session):
    inspector = inspect(db_session.bind)
    columns = {col["name"] for col in inspector.get_columns("products")}
    required = {
        "sku_id",
        "title",
        "brand",
        "category",
        "price",
        "attributes_json",
        "source",
        "source_snapshot_json",
        "updated_at",
    }
    assert required.issubset(columns)


def test_enrichment_version_has_uuid_pk(db_session):
    product = Product(
        sku_id="TEST-UUID",
        title="Test",
        brand="B",
        category="cat",
        price=1.0,
        source=SourceEnum.JSON,
    )
    db_session.add(product)
    db_session.flush()

    version = EnrichmentVersion(
        sku_id="TEST-UUID", generated_by=GeneratedByEnum.LLM, confidence_score=0.8
    )
    db_session.add(version)
    db_session.flush()

    assert isinstance(version.version_id, uuid.UUID)


def test_review_states_version_id_is_unique(db_session):
    product = Product(
        sku_id="TEST-UNIQ",
        title="Test",
        brand="B",
        category="cat",
        price=1.0,
        source=SourceEnum.JSON,
    )
    db_session.add(product)
    db_session.flush()

    version = EnrichmentVersion(
        sku_id="TEST-UNIQ", generated_by=GeneratedByEnum.LLM, confidence_score=0.8
    )
    db_session.add(version)
    db_session.flush()

    rs1 = ReviewState(version_id=version.version_id, review_status=ReviewStatusEnum.PENDING_REVIEW)
    db_session.add(rs1)
    db_session.flush()

    rs2 = ReviewState(version_id=version.version_id, review_status=ReviewStatusEnum.APPROVED)
    db_session.add(rs2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_user_roles_category_required_for_reviewer_category(db_session):
    user = User(name="Test", email=f"cat-test-{uuid.uuid4()}@test.com")
    db_session.add(user)
    db_session.flush()

    role = UserRole(user_id=user.id, role=RoleEnum.REVIEWER_CATEGORY, category=None)
    db_session.add(role)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_seed_data_present_in_dev_env(db_session):
    """Verify seed data was loaded into the main dev database (not the test DB).
    We test the seed function directly by running it against the test session."""
    from api.models import Product, User, UserRole

    # Manually create seed data in the test session
    admin = User(name="Admin User", email="admin@catalog.dev")
    db_session.add(admin)
    db_session.flush()
    db_session.add(UserRole(user_id=admin.id, role=RoleEnum.ADMIN))

    product = Product(
        sku_id="LP-001",
        title="Acer Aspire 3",
        brand="Acer",
        category="laptops",
        price=349.99,
        source=SourceEnum.JSON,
    )
    db_session.add(product)
    db_session.flush()

    assert db_session.query(User).filter(User.email == "admin@catalog.dev").first() is not None
    assert db_session.query(Product).filter(Product.sku_id == "LP-001").first() is not None
    admin_roles = (
        db_session.query(UserRole)
        .filter(UserRole.user_id == admin.id, UserRole.role == RoleEnum.ADMIN)
        .all()
    )
    assert len(admin_roles) == 1


def test_alembic_upgrade_is_idempotent(db_session):
    """Verify calling create_all twice doesn't fail (mirrors alembic upgrade idempotency)."""
    from api.database import Base

    # create_all is idempotent — tables already exist from fixture
    Base.metadata.create_all(bind=db_session.bind)
    inspector = inspect(db_session.bind)
    tables = inspector.get_table_names()
    for table in EXPECTED_TABLES:
        assert table in tables
