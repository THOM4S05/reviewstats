from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.timeutils import utc_now


class OrderType(str, enum.Enum):
    DINE_IN = "DINE_IN"
    TAKEAWAY = "TAKEAWAY"
    RETAIL = "RETAIL"


class MatchStatus(str, enum.Enum):
    HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
    PROBABLE = "PROBABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNMATCHED = "UNMATCHED"


class ScanpointStatus(str, enum.Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    LOST = "LOST"
    REPLACED = "REPLACED"


class SessionStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PosConnectionStatus(str, enum.Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"


class MembershipRole(str, enum.Enum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    ANALYST = "ANALYST"


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[MembershipRole] = mapped_column(Enum(MembershipRole, native_enum=False, length=20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Business(Base):
    __tablename__ = "businesses"
    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    google_place_id: Mapped[str | None] = mapped_column(String(255))
    google_review_url: Mapped[str] = mapped_column(String(1000))
    google_account_id: Mapped[str | None] = mapped_column(String(255))
    google_location_id: Mapped[str | None] = mapped_column(String(255))
    api_key_hash: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    orders: Mapped[list[Order]] = relationship(back_populates="business")


class BusinessLocation(Base):
    __tablename__ = "business_locations"
    __table_args__ = (UniqueConstraint("business_id", "external_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    external_ref: Mapped[str] = mapped_column(String(100))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    google_review_url: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServiceArea(Base):
    __tablename__ = "service_areas"
    __table_args__ = (UniqueConstraint("location_id", "external_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("business_locations.id"), index=True)
    external_ref: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Scanpoint(Base):
    __tablename__ = "scanpoints"
    __table_args__ = (UniqueConstraint("business_id", "serial_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    serial_number: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(100))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("business_locations.id"), index=True)
    status: Mapped[ScanpointStatus] = mapped_column(
        Enum(ScanpointStatus, native_enum=False, length=20), default=ScanpointStatus.PROVISIONED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanpointAssignment(Base):
    __tablename__ = "scanpoint_assignments"
    __table_args__ = (Index("ix_assignment_scanpoint_time", "scanpoint_id", "starts_at", "ends_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    scanpoint_id: Mapped[int] = mapped_column(ForeignKey("scanpoints.id"), index=True)
    service_area_id: Mapped[int] = mapped_column(ForeignKey("service_areas.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TableSession(Base):
    __tablename__ = "table_sessions"
    __table_args__ = (
        UniqueConstraint("business_id", "external_session_id"),
        Index("ix_table_session_area_time", "service_area_id", "opened_at", "closed_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("business_locations.id"), index=True)
    service_area_id: Mapped[int] = mapped_column(ForeignKey("service_areas.id"), index=True)
    external_session_id: Mapped[str | None] = mapped_column(String(150))
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False, length=20), default=SessionStatus.OPEN
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PosConnection(Base):
    __tablename__ = "pos_connections"
    __table_args__ = (UniqueConstraint("business_id", "provider", "external_location_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("business_locations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    external_location_id: Mapped[str] = mapped_column(String(150))
    status: Mapped[PosConnectionStatus] = mapped_column(
        Enum(PosConnectionStatus, native_enum=False, length=20), default=PosConnectionStatus.PENDING
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("business_id", "external_order_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    external_order_id: Mapped[str] = mapped_column(String(100))
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("business_locations.id"), index=True)
    service_area_id: Mapped[int | None] = mapped_column(ForeignKey("service_areas.id"), index=True)
    table_session_id: Mapped[int | None] = mapped_column(ForeignKey("table_sessions.id"), index=True)
    pos_connection_id: Mapped[int | None] = mapped_column(ForeignKey("pos_connections.id"), index=True)
    order_type: Mapped[OrderType] = mapped_column(Enum(OrderType, native_enum=False))
    table_number: Mapped[str | None] = mapped_column(String(50))
    staff_name: Mapped[str | None] = mapped_column(String(100))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    ordered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    business: Mapped[Business] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan")
    review_token: Mapped[ReviewToken] = relationship(back_populates="order", cascade="all, delete-orphan", uselist=False)
    scans: Mapped[list[ScanEvent]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column()
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    order: Mapped[Order] = relationship(back_populates="items")


class ReviewToken(Base):
    __tablename__ = "review_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    order: Mapped[Order] = relationship(back_populates="review_token")
    scans: Mapped[list[ScanEvent]] = relationship(back_populates="review_token")


class ScanEvent(Base):
    __tablename__ = "scan_events"
    __table_args__ = (Index("ix_scan_business_time", "business_id", "scanned_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    review_token_id: Mapped[int | None] = mapped_column(ForeignKey("review_tokens.id"), index=True)
    scanpoint_id: Mapped[int | None] = mapped_column(ForeignKey("scanpoints.id"), index=True)
    assignment_id: Mapped[int | None] = mapped_column(ForeignKey("scanpoint_assignments.id"), index=True)
    table_session_id: Mapped[int | None] = mapped_column(ForeignKey("table_sessions.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    redirected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolution_reason: Mapped[str | None] = mapped_column(String(255))
    review_token: Mapped[ReviewToken | None] = relationship(back_populates="scans")
    order: Mapped[Order | None] = relationship(back_populates="scans")
    match: Mapped[ReviewMatch | None] = relationship(back_populates="scan_event", uselist=False)


class GoogleReview(Base):
    __tablename__ = "google_reviews"
    __table_args__ = (UniqueConstraint("business_id", "google_review_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id"), index=True)
    google_review_id: Mapped[str] = mapped_column(String(500))
    provider: Mapped[str] = mapped_column(
        String(50), default="MOCK_GOOGLE", server_default="MOCK_GOOGLE"
    )
    reviewer_display_name: Mapped[str | None] = mapped_column(String(255))
    rating: Mapped[int] = mapped_column()
    comment: Mapped[str | None] = mapped_column(Text)
    google_create_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    google_update_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    match: Mapped[ReviewMatch | None] = relationship(back_populates="google_review", uselist=False)


class ReviewMatch(Base):
    __tablename__ = "review_matches"
    id: Mapped[int] = mapped_column(primary_key=True)
    google_review_id: Mapped[int] = mapped_column(ForeignKey("google_reviews.id", ondelete="CASCADE"), unique=True)
    scan_event_id: Mapped[int | None] = mapped_column(ForeignKey("scan_events.id"), unique=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    time_difference_seconds: Mapped[int | None] = mapped_column()
    candidate_count: Mapped[int] = mapped_column(default=0)
    second_best_gap_seconds: Mapped[int | None] = mapped_column()
    match_status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus, native_enum=False))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    algorithm_version: Mapped[str] = mapped_column(String(30), default="v1")
    explanation: Mapped[str | None] = mapped_column(Text)
    google_review: Mapped[GoogleReview] = relationship(back_populates="match")
    scan_event: Mapped[ScanEvent | None] = relationship(back_populates="match")


class AttributionCandidate(Base):
    __tablename__ = "attribution_candidates"
    __table_args__ = (UniqueConstraint("google_review_id", "scan_event_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    google_review_id: Mapped[int] = mapped_column(ForeignKey("google_reviews.id", ondelete="CASCADE"), index=True)
    scan_event_id: Mapped[int] = mapped_column(ForeignKey("scan_events.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    rank: Mapped[int] = mapped_column()
    evidence: Mapped[str] = mapped_column(Text)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AttributionAudit(Base):
    __tablename__ = "attribution_audits"
    id: Mapped[int] = mapped_column(primary_key=True)
    google_review_id: Mapped[int] = mapped_column(ForeignKey("google_reviews.id", ondelete="CASCADE"), index=True)
    scan_event_id: Mapped[int | None] = mapped_column(ForeignKey("scan_events.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    match_status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus, native_enum=False, length=20))
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    algorithm_version: Mapped[str] = mapped_column(String(30))
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
