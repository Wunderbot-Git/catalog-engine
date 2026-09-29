import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from api.database import Base

# --- Enums ---


class RoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    REVIEWER_GENERAL = "REVIEWER_GENERAL"
    REVIEWER_CATEGORY = "REVIEWER_CATEGORY"


class SourceEnum(str, enum.Enum):
    JSON = "json"
    CSV = "csv"
    EXCEL = "excel"
    ALGOLIA = "algolia"


class PriorityEnum(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReviewStatusEnum(str, enum.Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class GeneratedByEnum(str, enum.Enum):
    LLM = "llm"
    HUMAN = "human"
    SYSTEM = "system"


class AssignmentStatusEnum(str, enum.Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class CommentTypeEnum(str, enum.Enum):
    NOTE = "NOTE"
    PROMPT_FEEDBACK = "PROMPT_FEEDBACK"
    QUALITY_FLAG = "QUALITY_FLAG"


# --- Helpers ---


def _utcnow():
    return datetime.now(timezone.utc)


def _new_uuid():
    return uuid.uuid4()


# --- Models ---


class User(Base):
    __tablename__ = "users"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    roles = relationship("UserRole", back_populates="user", cascade="all, delete-orphan")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True, nullable=False
    )
    role = Column(Enum(RoleEnum, name="roleenum"), primary_key=True, nullable=False)
    category = Column(String, nullable=True)

    user = relationship("User", back_populates="roles")

    __table_args__ = (
        CheckConstraint(
            "(role != 'REVIEWER_CATEGORY') OR (category IS NOT NULL)",
            name="ck_category_required_for_reviewer_category",
        ),
    )


class Product(Base):
    __tablename__ = "products"

    sku_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    brand = Column(String, nullable=False, default="")
    category = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    attributes_json = Column(JSON, default=dict)
    source = Column(Enum(SourceEnum, name="sourceenum"), nullable=False)
    source_snapshot_json = Column(JSON, default=dict)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (Index("ix_products_category", "category"),)


class AuditResult(Base):
    __tablename__ = "audit_results"

    audit_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    sku_id = Column(String, ForeignKey("products.sku_id"), nullable=False)
    completeness_score = Column(Float, nullable=False)
    richness_score = Column(Float, nullable=False)
    missing_critical_fields = Column(JSON, default=list)
    low_quality_fields = Column(JSON, default=list)
    priority_for_enrichment = Column(Enum(PriorityEnum, name="priorityenum"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_audit_results_priority_created", "priority_for_enrichment", "created_at"),
    )


class EnrichmentVersion(Base):
    __tablename__ = "enrichment_versions"

    version_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    sku_id = Column(String, ForeignKey("products.sku_id"), nullable=False)
    parent_version_id = Column(
        PG_UUID(as_uuid=True), ForeignKey("enrichment_versions.version_id"), nullable=True
    )
    generated_by = Column(Enum(GeneratedByEnum, name="generatedbyenum"), nullable=False)
    model_name = Column(String, nullable=True)
    prompt_version = Column(String, nullable=True)
    use_case_tags = Column(JSON, default=list)
    persona_tags = Column(JSON, default=list)
    trust_signals = Column(JSON, default=dict)
    agent_summary = Column(Text, nullable=True)
    confidence_score = Column(Float, nullable=True)
    evidence_fields = Column(JSON, default=list)
    suggested_attributes = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    review_state = relationship("ReviewState", back_populates="version", uselist=False)

    __table_args__ = (
        Index(
            "ix_enrichment_versions_sku_created",
            "sku_id",
            created_at.desc(),
        ),
    )


class ReviewState(Base):
    __tablename__ = "review_states"

    review_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    version_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("enrichment_versions.version_id"),
        unique=True,
        nullable=False,
    )
    review_status = Column(Enum(ReviewStatusEnum, name="reviewstatusenum"), nullable=False)
    reviewer_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    priority_for_review = Column(Enum(PriorityEnum, name="priorityenum"), nullable=True)
    escalated = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    version = relationship("EnrichmentVersion", back_populates="review_state")

    __table_args__ = (Index("ix_review_states_status_created", "review_status", "created_at"),)


class ReviewComment(Base):
    __tablename__ = "review_comments"

    comment_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    sku_id = Column(String, ForeignKey("products.sku_id"), nullable=False)
    version_id = Column(
        PG_UUID(as_uuid=True), ForeignKey("enrichment_versions.version_id"), nullable=False
    )
    author_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    comment_type = Column(Enum(CommentTypeEnum, name="commenttypeenum"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Assignment(Base):
    __tablename__ = "assignments"

    assignment_id = Column(PG_UUID(as_uuid=True), primary_key=True, default=_new_uuid)
    sku_id = Column(String, ForeignKey("products.sku_id"), nullable=False)
    category = Column(String, nullable=False)
    assigned_role = Column(Enum(RoleEnum, name="roleenum"), nullable=False)
    assigned_to_user_id = Column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status = Column(
        Enum(AssignmentStatusEnum, name="assignmentstatusenum"),
        nullable=False,
        default=AssignmentStatusEnum.OPEN,
    )
    priority = Column(Enum(PriorityEnum, name="priorityenum"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_assignments_category_status_priority", "category", "status", "priority"),
    )
