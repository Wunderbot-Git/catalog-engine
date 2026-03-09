import json
import logging
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class StorageClient(ABC):
    @abstractmethod
    def write_json(self, path: str, data: list[dict]) -> None:
        """Write JSON data to the given path in cloud storage."""
        ...


class CloudStorageClient(StorageClient):
    """Real Cloud Storage client using the google-cloud-storage SDK."""

    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name

    def write_json(self, path: str, data: list[dict]) -> None:
        from google.cloud import storage

        client = storage.Client()
        blob = client.bucket(self.bucket_name).blob(path)
        blob.upload_from_string(
            json.dumps(data, default=str),
            content_type="application/json",
        )
        logger.info(
            "Wrote %d records to gs://%s/%s",
            len(data),
            self.bucket_name,
            path,
            extra={"job_id": "export"},
        )


class NoopStorageClient(StorageClient):
    """No-op client used when EXPORT_BUCKET is not configured."""

    def write_json(self, path: str, data: list[dict]) -> None:
        logger.info(
            "EXPORT_BUCKET not set, skipping Cloud Storage write (%d records)",
            len(data),
            extra={"job_id": "export"},
        )


_storage_client: StorageClient | None = None


def get_storage_client() -> StorageClient:
    global _storage_client
    if _storage_client is None:
        bucket = os.environ.get("EXPORT_BUCKET", "")
        if bucket:
            _storage_client = CloudStorageClient(bucket)
        else:
            _storage_client = NoopStorageClient()
    return _storage_client


def set_storage_client(client: StorageClient) -> None:
    global _storage_client
    _storage_client = client
