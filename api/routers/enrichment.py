import logging
import time
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import require_role
from api.dependencies.llm import get_llm_client
from api.llm.base import (
    LLMClient,
    LLMInvalidResponseError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
from api.llm.types import CategoryContext, ProductContext
from api.metrics import LLM_CALLS, LLM_LATENCY, SKUS_PROCESSED
from api.models import (
    EnrichmentVersion,
    GeneratedByEnum,
    PriorityEnum,
    Product,
    ReviewState,
    ReviewStatusEnum,
    RoleEnum,
    User,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class EnrichRequest(BaseModel):
    feedback: str = ""
    required_tags: List[str] = []
    forbidden_tags: List[str] = []
    focus: str = ""


@router.post("/skus/{sku_id}/enrich")
async def enrich_sku(
    sku_id: str,
    body: EnrichRequest = EnrichRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN, RoleEnum.REVIEWER_GENERAL)),
    llm_client: LLMClient = Depends(get_llm_client),
):
    product = db.query(Product).filter(Product.sku_id == sku_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="SKU not found")

    # Find latest existing version for parent linkage
    latest_version = (
        db.query(EnrichmentVersion)
        .filter(EnrichmentVersion.sku_id == sku_id)
        .order_by(desc(EnrichmentVersion.created_at))
        .first()
    )

    product_ctx = ProductContext(
        sku_id=product.sku_id,
        title=product.title,
        brand=product.brand,
        category=product.category,
        price=product.price,
        attributes=product.attributes_json or {},
    )
    category_ctx = CategoryContext(category=product.category)

    # Attempt LLM enrichment
    review_status = ReviewStatusEnum.PENDING_REVIEW
    priority_for_review = None
    enrichment_data = None

    llm_start = time.monotonic()
    try:
        result = await llm_client.enrich(product_ctx, category_ctx)
        LLM_LATENCY.observe(time.monotonic() - llm_start)
        LLM_CALLS.labels(outcome="success").inc()
        enrichment_data = result

        if result.confidence_score < 0.7:
            priority_for_review = PriorityEnum.HIGH

    except (LLMTimeoutError, LLMInvalidResponseError, LLMSchemaValidationError) as e:
        LLM_LATENCY.observe(time.monotonic() - llm_start)
        LLM_CALLS.labels(outcome="needs_review").inc()
        logger.warning(
            "LLM enrichment failed for sku_id=%s: %s", sku_id, e, extra={"sku_id": sku_id}
        )
        review_status = ReviewStatusEnum.NEEDS_REVIEW

    # Create enrichment version
    version = EnrichmentVersion(
        sku_id=sku_id,
        parent_version_id=latest_version.version_id if latest_version else None,
        generated_by=GeneratedByEnum.LLM,
        model_name=getattr(llm_client, "model_name", None),
    )

    if enrichment_data:
        version.use_case_tags = enrichment_data.use_case_tags
        version.persona_tags = enrichment_data.persona_tags
        version.trust_signals = enrichment_data.trust_signals.model_dump()
        version.agent_summary = enrichment_data.agent_summary
        version.confidence_score = enrichment_data.confidence_score
        version.evidence_fields = enrichment_data.evidence_fields

    db.add(version)
    db.flush()

    # Create review state
    rs = ReviewState(
        version_id=version.version_id,
        review_status=review_status,
        priority_for_review=priority_for_review,
    )
    db.add(rs)
    db.commit()
    SKUS_PROCESSED.labels(operation="enrichment").inc()

    logger.info(
        "Enrichment complete: sku_id=%s version_id=%s status=%s",
        sku_id,
        version.version_id,
        review_status.value,
        extra={"sku_id": sku_id, "version_id": str(version.version_id)},
    )

    return {
        "version_id": str(version.version_id),
        "review_status": review_status.value,
    }
