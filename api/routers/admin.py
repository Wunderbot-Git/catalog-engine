from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import require_role
from api.models import (
    Assignment,
    AssignmentStatusEnum,
    PriorityEnum,
    RoleEnum,
    User,
    UserRole,
)

router = APIRouter(prefix="/admin")


@router.get("/users")
async def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    users = db.query(User).all()
    result = []
    for u in users:
        roles = [{"role": r.role.value, "category": r.category} for r in u.roles]
        result.append(
            {
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "active": u.active,
                "roles": roles,
            }
        )
    return result


class AssignRoleRequest(BaseModel):
    role: RoleEnum
    category: Optional[str] = None


@router.post("/users/{user_id}/roles")
async def assign_role(
    user_id: UUID,
    body: AssignRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.role == RoleEnum.REVIEWER_CATEGORY and not body.category:
        raise HTTPException(status_code=422, detail="category required for REVIEWER_CATEGORY")

    existing = (
        db.query(UserRole).filter(UserRole.user_id == user_id, UserRole.role == body.role).first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Role already assigned")

    role = UserRole(
        user_id=user_id,
        role=body.role,
        category=body.category if body.role == RoleEnum.REVIEWER_CATEGORY else None,
    )
    db.add(role)
    db.commit()
    return {"status": "ok"}


class RemoveRoleRequest(BaseModel):
    role: RoleEnum


@router.delete("/users/{user_id}/roles")
async def remove_role(
    user_id: UUID,
    body: RemoveRoleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    role = (
        db.query(UserRole).filter(UserRole.user_id == user_id, UserRole.role == body.role).first()
    )
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    db.delete(role)
    db.commit()
    return {"status": "ok"}


class ReassignRequest(BaseModel):
    assigned_to_user_id: UUID
    priority: PriorityEnum = PriorityEnum.MEDIUM


@router.put("/assignments/{sku_id}")
async def reassign_sku(
    sku_id: str,
    body: ReassignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    assignment = db.query(Assignment).filter(Assignment.sku_id == sku_id).first()
    if assignment:
        assignment.assigned_to_user_id = body.assigned_to_user_id
        assignment.priority = body.priority
        assignment.status = AssignmentStatusEnum.OPEN
    else:
        assignment = Assignment(
            sku_id=sku_id,
            category="",
            assigned_role=RoleEnum.REVIEWER_GENERAL,
            assigned_to_user_id=body.assigned_to_user_id,
            status=AssignmentStatusEnum.OPEN,
            priority=body.priority,
        )
        db.add(assignment)

    db.commit()
    return {"status": "ok"}


class ThresholdsRequest(BaseModel):
    completeness_high: float = 0.6
    completeness_medium: float = 0.8
    richness_high: float = 0.5
    richness_medium: float = 0.7


# In-memory thresholds (would be persisted to DB in production)
_thresholds = ThresholdsRequest()


@router.put("/audit/thresholds")
async def update_thresholds(
    body: ThresholdsRequest,
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    global _thresholds
    _thresholds = body
    return {"status": "ok", "thresholds": body.model_dump()}


@router.get("/audit/thresholds")
async def get_thresholds(
    current_user: User = Depends(require_role(RoleEnum.ADMIN)),
):
    return _thresholds.model_dump()
