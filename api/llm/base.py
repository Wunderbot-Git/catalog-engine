from abc import ABC, abstractmethod

from api.llm.types import CategoryContext, EnrichmentResult, ProductContext


class LLMTimeoutError(Exception):
    pass


class LLMInvalidResponseError(Exception):
    pass


class LLMSchemaValidationError(Exception):
    pass


class LLMClient(ABC):
    @abstractmethod
    async def enrich(
        self,
        product: ProductContext,
        category_context: CategoryContext,
    ) -> EnrichmentResult: ...
