from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import MatchStatus, OrderType, ScanpointStatus


class InputModel(BaseModel):
    """Normalize form/API whitespace before applying field length constraints."""

    model_config = ConfigDict(str_strip_whitespace=True)


class OrderItemCreate(InputModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=100)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)


class OrderCreate(InputModel):
    external_order_id: str = Field(min_length=1, max_length=100)
    order_type: OrderType = OrderType.TAKEAWAY
    table_number: str | None = Field(default=None, max_length=50)
    staff_name: str | None = Field(default=None, max_length=100)
    ordered_at: datetime
    paid_at: datetime | None = None
    items: list[OrderItemCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_order(self):
        from app.timeutils import as_utc

        if self.paid_at and as_utc(self.paid_at) < as_utc(self.ordered_at):
            raise ValueError("Payment cannot precede the order")
        total = sum((item.price * item.quantity for item in self.items), Decimal("0"))
        if total > Decimal("99999999.99"):
            raise ValueError("Order total exceeds the supported monetary range")
        return self


class PosOrderUpsert(OrderCreate):
    provider: str = Field(default="PILOT", min_length=1, max_length=50)
    external_location_id: str = Field(default="main", min_length=1, max_length=150)
    external_session_id: str | None = Field(default=None, max_length=150)
    status: str = Field(default="COMPLETED", min_length=1, max_length=30)
    source_updated_at: datetime | None = None


class OrderItemRead(OrderItemCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class OrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    external_order_id: str
    business_id: int
    location_id: int | None
    service_area_id: int | None
    table_session_id: int | None
    order_type: OrderType
    staff_name: str | None
    total: Decimal
    ordered_at: datetime
    paid_at: datetime | None
    status: str
    items: list[OrderItemRead]


class ScanpointCreate(InputModel):
    serial_number: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    table_ref: str | None = Field(default=None, min_length=1, max_length=100)


class ScanpointAssign(InputModel):
    table_ref: str = Field(min_length=1, max_length=100)
    table_label: str | None = Field(default=None, max_length=100)


class ScanpointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    public_id: str
    serial_number: str
    label: str
    business_id: int
    location_id: int
    status: ScanpointStatus
    scan_url: str | None = None
    table_ref: str | None = None
    table_label: str | None = None


class ScanRead(BaseModel):
    id: int
    business_id: int
    scanpoint_id: int | None
    assignment_id: int | None
    table_session_id: int | None
    order_id: int | None
    scanned_at: datetime
    resolution_reason: str | None


class PosOrderResult(BaseModel):
    created: bool
    linked_scans: int
    order: OrderRead


class MockReviewCreate(InputModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)
    reviewer_display_name: str | None = Field(default="Test Customer", max_length=255)
    created_at: datetime
    google_review_id: str | None = Field(default=None, max_length=500)


class CustomerMockReviewCreate(InputModel):
    token: str = Field(min_length=20, max_length=128)
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)
    reviewer_display_name: str | None = Field(default=None, max_length=255)


class ReviewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    google_review_id: str
    provider: str
    reviewer_display_name: str | None
    rating: int
    comment: str | None
    google_create_time: datetime


class MatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    google_review_id: int
    scan_event_id: int | None
    order_id: int | None
    confidence_score: Decimal
    time_difference_seconds: int | None
    candidate_count: int
    second_best_gap_seconds: int | None
    match_status: MatchStatus


class ItemForm(BaseModel):
    name: str
    quantity: int = 1
    price: Decimal

    @model_validator(mode="after")
    def validate_values(self):
        if not self.name.strip() or self.quantity < 1 or self.price < 0:
            raise ValueError("Each item needs a name, positive quantity, and non-negative price")
        return self
