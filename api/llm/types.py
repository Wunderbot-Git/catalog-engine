import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, field_validator, model_validator

MAX_SUGGESTED_ATTRIBUTES = 10


class ProductContext(BaseModel):
    sku_id: str
    title: str
    brand: str = ""
    category: str
    price: float
    attributes: Dict[str, Any] = {}


class CategoryContext(BaseModel):
    category: str
    preferred_use_case_tags: List[str] = []
    preferred_persona_tags: List[str] = []


class TrustSignals(BaseModel):
    warranty_months: Optional[int] = None
    certifications: List[str] = []
    sustainability_notes: str = ""


def _slugify_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.strip().lower()).strip("_")


class SuggestedAttribute(BaseModel):
    """An attribute the product is missing.

    source=product_text: the value is stated in the product's own text (e.g. the title)
    but is not a structured attribute yet. source=missing: the attribute is expected for
    the category but the input has no data for it, so value must be null.
    """

    key: str
    value: Optional[Union[bool, int, float, str]] = None
    source: Literal["product_text", "missing"]
    reason: str = ""

    @field_validator("key")
    @classmethod
    def slugify_key(cls, v: str) -> str:
        slug = _slugify_key(v)
        if not slug:
            raise ValueError("suggested attribute key must not be empty")
        return slug

    @model_validator(mode="after")
    def value_matches_source(self) -> "SuggestedAttribute":
        if self.source == "missing" and self.value is not None:
            raise ValueError("value must be null when source is 'missing'")
        if self.source == "product_text" and self.value in (None, ""):
            raise ValueError("value is required when source is 'product_text'")
        return self


def drop_existing_attributes(
    suggestions: List[SuggestedAttribute], attributes: Dict[str, Any]
) -> List[SuggestedAttribute]:
    """Remove suggestions for attributes the product already has."""
    existing = {_slugify_key(k) for k in attributes}
    return [s for s in suggestions if s.key not in existing]


class EnrichmentResult(BaseModel):
    use_case_tags: List[str]
    persona_tags: List[str]
    trust_signals: TrustSignals
    agent_summary: str
    confidence_score: float
    evidence_fields: List[str] = []
    suggested_attributes: List[SuggestedAttribute] = []

    @field_validator("use_case_tags", "persona_tags")
    @classmethod
    def dedupe_and_slugify(cls, v: List[str]) -> List[str]:
        return list(dict.fromkeys(tag.lower().replace(" ", "_") for tag in v))

    @field_validator("agent_summary")
    @classmethod
    def summary_max_240(cls, v: str) -> str:
        if len(v) > 240:
            raise ValueError("agent_summary max 240 chars")
        return v

    @field_validator("confidence_score")
    @classmethod
    def score_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence_score must be 0.0–1.0")
        return v

    @field_validator("suggested_attributes")
    @classmethod
    def dedupe_and_cap_suggestions(cls, v: List[SuggestedAttribute]) -> List[SuggestedAttribute]:
        seen: set = set()
        unique = []
        for s in v:
            if s.key not in seen:
                seen.add(s.key)
                unique.append(s)
        return unique[:MAX_SUGGESTED_ATTRIBUTES]
