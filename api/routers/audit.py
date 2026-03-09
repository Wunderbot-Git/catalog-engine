import logging
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import require_role
from api.metrics import SKUS_PROCESSED
from api.models import AuditResult, Product, RoleEnum, User
from api.services.audit import compute_completeness_score, compute_priority, compute_richness_score

router = APIRouter()
logger = logging.getLogger(__name__)


class AuditRunRequest(BaseModel):
    sku_ids: Optional[List[str]] = None


@router.post("/audit/run")
async def audit_run(
    body: AuditRunRequest = AuditRunRequest(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    query = db.query(Product)
    if body.sku_ids:
        query = query.filter(Product.sku_id.in_(body.sku_ids))

    products = query.all()

    counts = {"processed": 0, "high": 0, "medium": 0, "low": 0}

    for product in products:
        completeness, missing = compute_completeness_score(product)
        richness, low_quality = compute_richness_score(product)
        priority = compute_priority(completeness, richness)

        stmt = insert(AuditResult).values(
            sku_id=product.sku_id,
            completeness_score=completeness,
            richness_score=richness,
            missing_critical_fields=missing,
            low_quality_fields=low_quality,
            priority_for_enrichment=priority,
        )
        db.execute(stmt)

        counts["processed"] += 1
        counts[priority.value.lower()] += 1

    db.commit()
    SKUS_PROCESSED.labels(operation="audit").inc(counts["processed"])
    logger.info(
        "Audit complete: processed=%d high=%d medium=%d low=%d",
        counts["processed"],
        counts["high"],
        counts["medium"],
        counts["low"],
        extra={"job_id": "audit"},
    )
    return counts
