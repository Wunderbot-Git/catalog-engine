import enum
import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.database import get_db
from api.dependencies.auth import get_current_user
from api.dependencies.llm import get_llm_client
from api.llm.base import (
    LLMClient,
    LLMInvalidResponseError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
from api.llm.types import (
    CategoryContext,
    ProductContext,
    SuggestedAttribute,
    TrustSignals,
    drop_existing_attributes,
)
from api.metrics import REVIEW_ACTIONS, TIME_TO_APPROVAL
from api.models import (
    Assignment,
    AssignmentStatusEnum,
    EnrichmentVersion,
    GeneratedByEnum,
    PriorityEnum,
    Product,
    ReviewComment,
    ReviewState,
    ReviewStatusEnum,
    RoleEnum,
    User,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class ReviewAction(str, enum.Enum):
    APPROVE = "approve"
    APPROVE_WITH_EDITS = "approve_with_edits"
    REJECT = "reject"
    ESCALATE = "escalate"
    COMMENT = "comment"
    REENRICH = "reenrich"


class EditedEnrichment(BaseModel):
    use_case_tags: List[str]
    persona_tags: List[str]
    trust_signals: TrustSignals
    agent_summary: str
    confidence_score: float
    evidence_fields: List[str] = []
    suggested_attributes: List[SuggestedAttribute] = []


class ReviewRequest(BaseModel):
    action: ReviewAction
    version_id: UUID
    rejection_reason: Optional[str] = None
    edited_enrichment: Optional[EditedEnrichment] = None
    comment_type: Optional[str] = None
    comment_body: Optional[str] = None
    escalate_to_user_id: Optional[UUID] = None
    escalate_reason: Optional[str] = None
    reenrich_feedback: Optional[str] = None


@router.post("/skus/{sku_id}/review")
async def review_sku(
    sku_id: str,
    body: ReviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    llm_client: LLMClient = Depends(get_llm_client),
):
    # Verify SKU exists
    product = db.query(Product).filter(Product.sku_id == sku_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="SKU not found")

    # Enforce REVIEWER_CATEGORY restriction
    user_roles = {r.role for r in current_user.roles}
    if not user_roles.intersection({RoleEnum.ADMIN, RoleEnum.REVIEWER_GENERAL}):
        # Must be REVIEWER_CATEGORY — check category
        user_categories = {
            r.category for r in current_user.roles if r.role == RoleEnum.REVIEWER_CATEGORY
        }
        if product.category not in user_categories:
            raise HTTPException(status_code=403, detail="Not authorized for this category")

    # Verify version exists and belongs to this SKU
    version = (
        db.query(EnrichmentVersion)
        .filter(
            EnrichmentVersion.version_id == body.version_id,
            EnrichmentVersion.sku_id == sku_id,
        )
        .first()
    )
    if not version:
        raise HTTPException(status_code=404, detail="Version not found for this SKU")

    review_state = db.query(ReviewState).filter(ReviewState.version_id == body.version_id).first()
    if not review_state:
        raise HTTPException(status_code=404, detail="Review state not found")

    if body.action == ReviewAction.APPROVE:
        review_state.review_status = ReviewStatusEnum.APPROVED
        review_state.reviewer_id = current_user.id
        review_state.reviewed_at = datetime.now(timezone.utc)

    elif body.action == ReviewAction.APPROVE_WITH_EDITS:
        if not body.edited_enrichment:
            raise HTTPException(status_code=422, detail="edited_enrichment required")

        # Create new human version
        new_version = EnrichmentVersion(
            sku_id=sku_id,
            parent_version_id=version.version_id,
            generated_by=GeneratedByEnum.HUMAN,
            use_case_tags=body.edited_enrichment.use_case_tags,
            persona_tags=body.edited_enrichment.persona_tags,
            trust_signals=body.edited_enrichment.trust_signals.model_dump(),
            agent_summary=body.edited_enrichment.agent_summary,
            confidence_score=body.edited_enrichment.confidence_score,
            evidence_fields=body.edited_enrichment.evidence_fields,
            suggested_attributes=[
                s.model_dump() for s in body.edited_enrichment.suggested_attributes
            ],
        )
        db.add(new_version)
        db.flush()

        new_rs = ReviewState(
            version_id=new_version.version_id,
            review_status=ReviewStatusEnum.APPROVED,
            reviewer_id=current_user.id,
            reviewed_at=datetime.now(timezone.utc),
        )
        db.add(new_rs)

    elif body.action == ReviewAction.REJECT:
        if not body.rejection_reason:
            raise HTTPException(status_code=422, detail="rejection_reason required")
        review_state.review_status = ReviewStatusEnum.REJECTED
        review_state.rejection_reason = body.rejection_reason
        review_state.reviewer_id = current_user.id
        review_state.reviewed_at = datetime.now(timezone.utc)

    elif body.action == ReviewAction.ESCALATE:
        if not body.escalate_to_user_id or not body.escalate_reason:
            raise HTTPException(
                status_code=422, detail="escalate_to_user_id and escalate_reason required"
            )
        review_state.review_status = ReviewStatusEnum.ESCALATED
        review_state.escalated = True
        review_state.reviewer_id = current_user.id
        review_state.reviewed_at = datetime.now(timezone.utc)

        assignment = Assignment(
            sku_id=sku_id,
            category=product.category,
            assigned_role=RoleEnum.REVIEWER_GENERAL,
            assigned_to_user_id=body.escalate_to_user_id,
            status=AssignmentStatusEnum.OPEN,
            priority=PriorityEnum.HIGH,
        )
        db.add(assignment)

    elif body.action == ReviewAction.COMMENT:
        if not body.comment_body:
            raise HTTPException(status_code=422, detail="comment_body required")
        comment = ReviewComment(
            sku_id=sku_id,
            version_id=body.version_id,
            author_id=current_user.id,
            comment_type=body.comment_type or "NOTE",
            body=body.comment_body,
        )
        db.add(comment)
        # Comment does NOT change review status

    elif body.action == ReviewAction.REENRICH:
        # Trigger new LLM enrichment
        product_ctx = ProductContext(
            sku_id=product.sku_id,
            title=product.title,
            brand=product.brand,
            category=product.category,
            price=product.price,
            attributes=product.attributes_json or {},
        )
        category_ctx = CategoryContext(category=product.category)

        new_review_status = ReviewStatusEnum.PENDING_REVIEW
        enrichment_data = None
        priority_for_review = None

        try:
            result = await llm_client.enrich(product_ctx, category_ctx)
            enrichment_data = result
            if result.confidence_score < 0.7:
                priority_for_review = PriorityEnum.HIGH
        except (LLMTimeoutError, LLMInvalidResponseError, LLMSchemaValidationError):
            new_review_status = ReviewStatusEnum.NEEDS_REVIEW

        new_version = EnrichmentVersion(
            sku_id=sku_id,
            parent_version_id=version.version_id,
            generated_by=GeneratedByEnum.LLM,
            model_name=getattr(llm_client, "model_name", None),
        )
        if enrichment_data:
            new_version.use_case_tags = enrichment_data.use_case_tags
            new_version.persona_tags = enrichment_data.persona_tags
            new_version.trust_signals = enrichment_data.trust_signals.model_dump()
            new_version.agent_summary = enrichment_data.agent_summary
            new_version.confidence_score = enrichment_data.confidence_score
            new_version.evidence_fields = enrichment_data.evidence_fields
            new_version.suggested_attributes = [
                s.model_dump()
                for s in drop_existing_attributes(
                    enrichment_data.suggested_attributes, product_ctx.attributes
                )
            ]

        db.add(new_version)
        db.flush()

        new_rs = ReviewState(
            version_id=new_version.version_id,
            review_status=new_review_status,
            priority_for_review=priority_for_review,
        )
        db.add(new_rs)

    db.commit()

    REVIEW_ACTIONS.labels(action=body.action.value).inc()
    if body.action in (ReviewAction.APPROVE, ReviewAction.APPROVE_WITH_EDITS):
        if version.created_at:
            elapsed = (datetime.now(timezone.utc) - version.created_at).total_seconds()
            TIME_TO_APPROVAL.observe(elapsed)

    logger.info(
        "Review action=%s sku_id=%s version_id=%s by user=%s",
        body.action.value,
        sku_id,
        body.version_id,
        current_user.email,
        extra={"sku_id": sku_id, "version_id": str(body.version_id)},
    )
    return {"status": "ok"}


@router.get("/skus/{sku_id}/comments")
async def get_comments(
    sku_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.sku_id == sku_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="SKU not found")

    comments = (
        db.query(ReviewComment, User.email)
        .join(User, ReviewComment.author_id == User.id)
        .filter(ReviewComment.sku_id == sku_id)
        .order_by(desc(ReviewComment.created_at))
        .all()
    )

    return [
        {
            "comment_id": str(c.comment_id),
            "version_id": str(c.version_id),
            "author_email": email,
            "comment_type": c.comment_type.value if c.comment_type else "NOTE",
            "body": c.body,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, email in comments
    ]


@router.get("/skus/{sku_id}/versions")
async def get_versions(
    sku_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    product = db.query(Product).filter(Product.sku_id == sku_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="SKU not found")

    versions = (
        db.query(EnrichmentVersion)
        .filter(EnrichmentVersion.sku_id == sku_id)
        .order_by(desc(EnrichmentVersion.created_at))
        .all()
    )

    result = []
    for v in versions:
        rs = v.review_state
        result.append(
            {
                "version_id": str(v.version_id),
                "parent_version_id": str(v.parent_version_id) if v.parent_version_id else None,
                "generated_by": v.generated_by.value if v.generated_by else None,
                "model_name": v.model_name,
                "use_case_tags": v.use_case_tags or [],
                "persona_tags": v.persona_tags or [],
                "trust_signals": v.trust_signals or {},
                "agent_summary": v.agent_summary,
                "confidence_score": v.confidence_score,
                "evidence_fields": v.evidence_fields or [],
                "suggested_attributes": v.suggested_attributes or [],
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "review_status": rs.review_status.value if rs else None,
                "reviewer_id": str(rs.reviewer_id) if rs and rs.reviewer_id else None,
                "reviewed_at": rs.reviewed_at.isoformat() if rs and rs.reviewed_at else None,
            }
        )

    return result
