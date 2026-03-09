import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.algolia import AlgoliaClient, get_algolia_client
from api.dependencies.auth import require_role
from api.models import RoleEnum, User
from api.services.export import get_latest_approved_per_sku

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/algolia/sync")
async def algolia_sync(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
    algolia_client: AlgoliaClient = Depends(get_algolia_client),
):
    records = get_latest_approved_per_sku(db)

    objects = []
    for r in records:
        objects.append(
            {
                "objectID": r["sku_id"],
                "use_case_tags": r["use_case_tags"],
                "persona_tags": r["persona_tags"],
                "trust_signals": r["trust_signals"],
                "agent_summary": r["agent_summary"],
                "confidence_score": r["confidence_score"],
            }
        )

    count = 0
    if objects:
        count = algolia_client.partial_update_objects(objects)

    logger.info("Algolia sync complete: count_synced=%d", count, extra={"job_id": "algolia_sync"})
    return {"count_synced": count}
