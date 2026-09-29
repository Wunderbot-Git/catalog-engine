from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import get_current_user
from api.models import (
    AuditResult,
    EnrichmentVersion,
    PriorityEnum,
    Product,
    ReviewState,
    ReviewStatusEnum,
    User,
)

router = APIRouter()


@router.get("/skus")
async def list_skus(
    category: Optional[str] = None,
    status: Optional[ReviewStatusEnum] = None,
    priority: Optional[PriorityEnum] = None,
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Product)

    if category:
        query = query.filter(Product.category == category)

    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(Product.sku_id.ilike(pattern), Product.title.ilike(pattern)))

    # Filter by review status: join through enrichment_versions -> review_states
    if status:
        query = (
            query.join(EnrichmentVersion, EnrichmentVersion.sku_id == Product.sku_id)
            .join(ReviewState, ReviewState.version_id == EnrichmentVersion.version_id)
            .filter(ReviewState.review_status == status)
        )

    # Filter by audit priority
    if priority:
        query = query.join(AuditResult, AuditResult.sku_id == Product.sku_id).filter(
            AuditResult.priority_for_enrichment == priority
        )

    total = query.count()
    offset = (page - 1) * page_size
    items = query.offset(offset).limit(page_size).all()

    return {
        "items": [_product_to_dict(p) for p in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/skus/{sku_id}")
async def get_sku(
    sku_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.sku_id == sku_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="SKU not found")

    # Latest enrichment version
    latest_version = (
        db.query(EnrichmentVersion)
        .filter(EnrichmentVersion.sku_id == sku_id)
        .order_by(desc(EnrichmentVersion.created_at))
        .first()
    )

    # Latest audit result
    latest_audit = (
        db.query(AuditResult)
        .filter(AuditResult.sku_id == sku_id)
        .order_by(desc(AuditResult.created_at))
        .first()
    )

    result = _product_to_dict(product)

    if latest_version:
        review_state = latest_version.review_state
        result["enrichment"] = {
            "version_id": str(latest_version.version_id),
            "generated_by": latest_version.generated_by.value
            if latest_version.generated_by
            else None,
            "use_case_tags": latest_version.use_case_tags or [],
            "persona_tags": latest_version.persona_tags or [],
            "trust_signals": latest_version.trust_signals or {},
            "agent_summary": latest_version.agent_summary,
            "confidence_score": latest_version.confidence_score,
            "evidence_fields": latest_version.evidence_fields or [],
            "suggested_attributes": latest_version.suggested_attributes or [],
            "created_at": latest_version.created_at.isoformat()
            if latest_version.created_at
            else None,
            "review_status": review_state.review_status.value if review_state else None,
        }
    else:
        result["enrichment"] = None

    if latest_audit:
        result["audit"] = {
            "audit_id": str(latest_audit.audit_id),
            "completeness_score": latest_audit.completeness_score,
            "richness_score": latest_audit.richness_score,
            "missing_critical_fields": latest_audit.missing_critical_fields or [],
            "low_quality_fields": latest_audit.low_quality_fields or [],
            "priority_for_enrichment": latest_audit.priority_for_enrichment.value
            if latest_audit.priority_for_enrichment
            else None,
        }
    else:
        result["audit"] = None

    return result


def _product_to_dict(product: Product) -> dict:
    return {
        "sku_id": product.sku_id,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "price": product.price,
        "attributes": product.attributes_json or {},
        "source": product.source.value if product.source else None,
        "updated_at": product.updated_at.isoformat() if product.updated_at else None,
    }
