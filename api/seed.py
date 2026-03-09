"""Seed data for development. Guarded by ENV=development."""

from api.config import ENV
from api.database import SessionLocal
from api.models import (
    Product,
    RoleEnum,
    SourceEnum,
    User,
    UserRole,
)


def seed():
    if ENV != "development":
        print(f"Skipping seed: ENV={ENV} (requires 'development')")
        return

    db = SessionLocal()
    try:
        # Users
        admin = User(name="Admin User", email="admin@catalog.dev")
        reviewer_general = User(name="General Reviewer", email="reviewer@catalog.dev")
        reviewer_category = User(name="Laptop Reviewer", email="laptops@catalog.dev")

        for user in [admin, reviewer_general, reviewer_category]:
            existing = db.query(User).filter(User.email == user.email).first()
            if existing:
                continue
            db.add(user)
        db.flush()

        # Fetch users for role assignment
        admin = db.query(User).filter(User.email == "admin@catalog.dev").one()
        reviewer_general = db.query(User).filter(User.email == "reviewer@catalog.dev").one()
        reviewer_category = db.query(User).filter(User.email == "laptops@catalog.dev").one()

        roles = [
            UserRole(user_id=admin.id, role=RoleEnum.ADMIN),
            UserRole(user_id=reviewer_general.id, role=RoleEnum.REVIEWER_GENERAL),
            UserRole(
                user_id=reviewer_category.id,
                role=RoleEnum.REVIEWER_CATEGORY,
                category="laptops",
            ),
        ]
        for role in roles:
            existing = (
                db.query(UserRole)
                .filter(UserRole.user_id == role.user_id, UserRole.role == role.role)
                .first()
            )
            if not existing:
                db.add(role)

        # Products
        products = [
            Product(
                sku_id="LP-001",
                title='Acer Aspire 3 15.6" Laptop Intel Core i3',
                brand="Acer",
                category="laptops",
                price=349.99,
                attributes_json={
                    "processor": "Intel Core i3-1215U",
                    "ram_gb": 8,
                    "storage_gb": 256,
                    "display_inches": 15.6,
                },
                source=SourceEnum.JSON,
                source_snapshot_json={},
            ),
            Product(
                sku_id="LP-002",
                title="ASUS ProArt Studiobook 16 OLED Creator Laptop",
                brand="ASUS",
                category="laptops",
                price=2499.00,
                attributes_json={
                    "processor": "Intel Core Ultra 9 185H with NPU",
                    "ram_gb": 64,
                    "storage_gb": 2000,
                    "gpu": "NVIDIA RTX 4070",
                },
                source=SourceEnum.JSON,
                source_snapshot_json={},
            ),
        ]
        for product in products:
            existing = db.query(Product).filter(Product.sku_id == product.sku_id).first()
            if not existing:
                db.add(product)

        db.commit()
        print("Seed data loaded successfully.")
    except Exception as e:
        db.rollback()
        print(f"Seed failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed()
