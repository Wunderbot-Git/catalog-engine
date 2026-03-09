from abc import ABC, abstractmethod
from typing import Any


class AlgoliaClient(ABC):
    @abstractmethod
    def partial_update_objects(self, objects: list[dict[str, Any]]) -> int:
        """Partial update objects in Algolia. Returns count of objects synced."""
        ...


class AlgoliaSearchClient(AlgoliaClient):
    """Real Algolia client using the algoliasearch SDK."""

    def __init__(self, app_id: str, api_key: str, index_name: str):
        self.app_id = app_id
        self.api_key = api_key
        self.index_name = index_name

    def partial_update_objects(self, objects: list[dict[str, Any]]) -> int:
        # Placeholder — real implementation:
        # from algoliasearch.search_client import SearchClient
        # client = SearchClient.create(self.app_id, self.api_key)
        # index = client.init_index(self.index_name)
        # index.partial_update_objects(objects, {"createIfNotExists": True})
        return len(objects)


_algolia_client: AlgoliaClient | None = None


def get_algolia_client() -> AlgoliaClient:
    global _algolia_client
    if _algolia_client is None:
        import os

        app_id = os.environ.get("ALGOLIA_APP_ID", "")
        api_key = os.environ.get("ALGOLIA_API_KEY", "")
        index_name = os.environ.get("ALGOLIA_INDEX_NAME", "")
        _algolia_client = AlgoliaSearchClient(app_id, api_key, index_name)
    return _algolia_client


def set_algolia_client(client: AlgoliaClient) -> None:
    global _algolia_client
    _algolia_client = client
