import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import require_role
from api.dependencies.storage import StorageClient, get_storage_client
from api.models import RoleEnum, User
from api.services.export import get_latest_approved_per_sku

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/exports/latest")
async def export_latest(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
    storage: StorageClient = Depends(get_storage_client),
):
    records = get_latest_approved_per_sku(db)
    storage.write_json("catalog_agent_ready.json", records)
    return records
