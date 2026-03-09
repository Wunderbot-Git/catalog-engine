from sqlalchemy import func
from sqlalchemy.orm import Session

from api.models import EnrichmentVersion, Product, ReviewState, ReviewStatusEnum


def get_latest_approved_per_sku(db: Session) -> list[dict]:
    """Return the latest APPROVED enrichment version per SKU, joined with product data."""
    # Subquery: max created_at per sku where status = APPROVED
    latest_approved = (
        db.query(
            EnrichmentVersion.sku_id,
            func.max(EnrichmentVersion.created_at).label("max_created"),
        )
        .join(ReviewState, ReviewState.version_id == EnrichmentVersion.version_id)
        .filter(ReviewState.review_status == ReviewStatusEnum.APPROVED)
        .group_by(EnrichmentVersion.sku_id)
        .subquery()
    )

    rows = (
        db.query(EnrichmentVersion, Product, ReviewState)
        .join(Product, Product.sku_id == EnrichmentVersion.sku_id)
        .join(ReviewState, ReviewState.version_id == EnrichmentVersion.version_id)
        .join(
            latest_approved,
            (EnrichmentVersion.sku_id == latest_approved.c.sku_id)
            & (EnrichmentVersion.created_at == latest_approved.c.max_created),
        )
        .all()
    )

    results = []
    for version, product, review_state in rows:
        results.append(
            {
                "sku_id": product.sku_id,
                "title": product.title,
                "brand": product.brand,
                "category": product.category,
                "price": product.price,
                "use_case_tags": version.use_case_tags or [],
                "persona_tags": version.persona_tags or [],
                "trust_signals": version.trust_signals or {},
                "agent_summary": version.agent_summary,
                "confidence_score": version.confidence_score,
                "version_id": str(version.version_id),
                "approved_at": review_state.reviewed_at.isoformat()
                if review_state.reviewed_at
                else None,
            }
        )

    return results
