from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


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


class EnrichmentResult(BaseModel):
    use_case_tags: List[str]
    persona_tags: List[str]
    trust_signals: TrustSignals
    agent_summary: str
    confidence_score: float
    evidence_fields: List[str] = []

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
