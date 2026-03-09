from typing import Any, Dict, List, Literal

from pydantic import BaseModel, field_validator


class ProductIngestionItem(BaseModel):
    sku_id: str
    title: str
    brand: str = ""
    category: str
    price: float
    attributes: Dict[str, Any] = {}
    source: Literal["json", "csv", "excel", "algolia"]
    source_snapshot: Dict[str, Any] = {}

    @field_validator("sku_id")
    @classmethod
    def sku_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("sku_id must not be empty")
        return v.strip()

    @field_validator("price")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("price must be >= 0")
        return v


class IngestionJobRequest(BaseModel):
    items: List[ProductIngestionItem]

    @field_validator("items")
    @classmethod
    def items_not_empty(cls, v: List[ProductIngestionItem]) -> List[ProductIngestionItem]:
        if not v:
            raise ValueError("items list must not be empty")
        return v
