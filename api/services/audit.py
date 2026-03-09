from typing import List, Tuple

from api.models import PriorityEnum, Product


def compute_completeness_score(product: Product) -> Tuple[float, List[str]]:
    """Weighted field presence score per specs.md section 8."""
    score = 0.0
    missing = []

    if product.title and product.title.strip():
        score += 0.20
    else:
        missing.append("title")

    if product.brand and product.brand.strip():
        score += 0.15
    else:
        missing.append("brand")

    if product.category and product.category.strip():
        score += 0.15
    else:
        missing.append("category")

    if product.price is not None and product.price >= 0:
        score += 0.15
    else:
        missing.append("price")

    attrs = product.attributes_json or {}
    if len(attrs) >= 1:
        score += 0.35
    else:
        missing.append("attributes")

    return round(score, 2), missing


def compute_richness_score(product: Product) -> Tuple[float, List[str]]:
    """Semantic quality score per specs.md section 8."""
    score = 0.0
    low_quality = []

    if product.title and len(product.title) >= 30:
        score += 0.25
    else:
        low_quality.append("title_too_short")

    attrs = product.attributes_json or {}
    if len(attrs) >= 5:
        score += 0.25
    else:
        low_quality.append("few_attributes")

    has_numeric = any(isinstance(v, (int, float)) for v in attrs.values())
    if has_numeric:
        score += 0.25
    else:
        low_quality.append("no_numeric_attributes")

    if product.brand and len(product.brand.split()) >= 2:
        score += 0.25
    else:
        low_quality.append("brand_single_word")

    return round(score, 2), low_quality


def compute_priority(completeness: float, richness: float) -> PriorityEnum:
    """Priority classification per specs.md section 8."""
    if completeness < 0.6 or richness < 0.5:
        return PriorityEnum.HIGH
    if completeness < 0.8 or richness < 0.7:
        return PriorityEnum.MEDIUM
    return PriorityEnum.LOW
