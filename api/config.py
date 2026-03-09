import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://catalog:catalog@localhost:5432/catalog_engine"
)
DATABASE_URL_TEST = os.environ.get("DATABASE_URL_TEST")
ENV = os.environ.get("ENV", "development")

GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
