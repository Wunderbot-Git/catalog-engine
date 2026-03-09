from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import get_current_user
from api.metrics import PENDING_REVIEW_GAUGE
from api.models import (
    ReviewState,
    ReviewStatusEnum,
    User,
)

router = APIRouter()


@router.get("/dashboard/stats")
async def dashboard_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Backlog counts
    pending_count = (
        db.query(func.count(ReviewState.review_id))
        .filter(ReviewState.review_status == ReviewStatusEnum.PENDING_REVIEW)
        .scalar()
    )
    escalated_count = (
        db.query(func.count(ReviewState.review_id))
        .filter(ReviewState.review_status == ReviewStatusEnum.ESCALATED)
        .scalar()
    )

    # 7-day throughput (approved per day)
    now = datetime.now(timezone.utc)
    seven_days_ago = now - timedelta(days=7)

    daily_approved = (
        db.query(
            func.date_trunc("day", ReviewState.reviewed_at).label("day"),
            func.count(ReviewState.review_id).label("count"),
        )
        .filter(
            ReviewState.review_status == ReviewStatusEnum.APPROVED,
            ReviewState.reviewed_at >= seven_days_ago,
        )
        .group_by(func.date_trunc("day", ReviewState.reviewed_at))
        .order_by(func.date_trunc("day", ReviewState.reviewed_at))
        .all()
    )

    throughput = [
        {"date": row.day.isoformat() if row.day else None, "count": row.count}
        for row in daily_approved
    ]

    # Top 5 rejection reasons
    top_rejections = (
        db.query(
            ReviewState.rejection_reason,
            func.count(ReviewState.review_id).label("count"),
        )
        .filter(
            ReviewState.review_status == ReviewStatusEnum.REJECTED,
            ReviewState.rejection_reason.isnot(None),
        )
        .group_by(ReviewState.rejection_reason)
        .order_by(func.count(ReviewState.review_id).desc())
        .limit(5)
        .all()
    )

    rejection_reasons = [
        {"reason": row.rejection_reason, "count": row.count} for row in top_rejections
    ]

    PENDING_REVIEW_GAUGE.set(pending_count or 0)

    return {
        "pending_review_count": pending_count,
        "escalated_count": escalated_count,
        "throughput": throughput,
        "top_rejection_reasons": rejection_reasons,
    }
