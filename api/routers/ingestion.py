import logging

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import require_role
from api.metrics import SKUS_PROCESSED
from api.models import Product, RoleEnum, SourceEnum, User
from api.schemas.ingestion import IngestionJobRequest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/ingest/jobs")
async def ingest_jobs(
    body: IngestionJobRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    count_ok = 0
    count_failed = 0
    errors = []

    for item in body.items:
        try:
            stmt = (
                insert(Product)
                .values(
                    sku_id=item.sku_id,
                    title=item.title,
                    brand=item.brand,
                    category=item.category,
                    price=item.price,
                    attributes_json=item.attributes,
                    source=SourceEnum(item.source),
                    source_snapshot_json=item.source_snapshot,
                )
                .on_conflict_do_update(
                    index_elements=["sku_id"],
                    set_={
                        "title": item.title,
                        "brand": item.brand,
                        "category": item.category,
                        "price": item.price,
                        "attributes_json": item.attributes,
                        "source": SourceEnum(item.source),
                        "source_snapshot_json": item.source_snapshot,
                    },
                )
            )
            db.execute(stmt)
            db.flush()
            count_ok += 1
        except Exception as e:
            db.rollback()
            count_failed += 1
            errors.append({"sku_id": item.sku_id, "reason": str(e)})
            logger.warning(
                "Ingestion failed for sku_id=%s: %s", item.sku_id, e, extra={"sku_id": item.sku_id}
            )

    if count_ok > 0:
        db.commit()
        SKUS_PROCESSED.labels(operation="ingestion").inc(count_ok)

    logger.info(
        "Ingestion complete: ok=%d failed=%d",
        count_ok,
        count_failed,
        extra={"job_id": "ingestion"},
    )

    return {"count_ok": count_ok, "count_failed": count_failed, "errors": errors}
