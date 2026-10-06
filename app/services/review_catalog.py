from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import (
    Business,
    BusinessLocation,
    GoogleReview,
    Order,
    ReviewMatch,
    ScanEvent,
)
from app.services.orders import get_default_business
from app.timeutils import as_utc


@dataclass(frozen=True)
class ReviewCatalogRow:
    review: GoogleReview
    match: ReviewMatch | None
    scan: ScanEvent | None
    order: Order | None
    explanation: dict
    created_at_local: datetime
    updated_at_local: datetime
    retrieved_at_local: datetime
    scanned_at_local: datetime | None
    ordered_at_local: datetime | None
    paid_at_local: datetime | None


def _local_time(value: datetime | None, timezone: ZoneInfo) -> datetime | None:
    return as_utc(value).astimezone(timezone) if value is not None else None


def build_review_catalog(db: Session, business: Business | None = None) -> dict:
    business = business or get_default_business(db)
    location = db.scalar(
        select(BusinessLocation)
        .where(BusinessLocation.business_id == business.id)
        .order_by(BusinessLocation.is_active.desc(), BusinessLocation.id)
        .limit(1)
    )
    timezone_name = location.timezone if location else get_settings().default_timezone
    timezone = ZoneInfo(timezone_name)

    reviews = list(
        db.scalars(
            select(GoogleReview)
            .options(selectinload(GoogleReview.match).selectinload(ReviewMatch.scan_event))
            .where(GoogleReview.business_id == business.id)
            .order_by(GoogleReview.google_create_time.desc(), GoogleReview.id.desc())
        ).all()
    )
    order_id_by_review = {
        review.id: (
            review.match.order_id
            or (review.match.scan_event.order_id if review.match.scan_event else None)
        )
        for review in reviews
        if review.match is not None
    }
    order_ids = {order_id for order_id in order_id_by_review.values() if order_id is not None}
    orders = (
        {
            order.id: order
            for order in db.scalars(
                select(Order)
                .options(selectinload(Order.items))
                .where(Order.id.in_(order_ids), Order.business_id == business.id)
            ).all()
        }
        if order_ids
        else {}
    )

    rows = []
    for review in reviews:
        match = review.match
        scan = match.scan_event if match else None
        order = orders.get(order_id_by_review.get(review.id)) if match else None
        try:
            explanation = json.loads(match.explanation) if match and match.explanation else {}
        except json.JSONDecodeError:
            explanation = {}
        rows.append(
            ReviewCatalogRow(
                review=review,
                match=match,
                scan=scan,
                order=order,
                explanation=explanation,
                created_at_local=_local_time(review.google_create_time, timezone),
                updated_at_local=_local_time(review.google_update_time, timezone),
                retrieved_at_local=_local_time(review.retrieved_at, timezone),
                scanned_at_local=_local_time(scan.scanned_at, timezone) if scan else None,
                ordered_at_local=_local_time(order.ordered_at, timezone) if order else None,
                paid_at_local=_local_time(order.paid_at, timezone) if order else None,
            )
        )

    return {
        "business": business,
        "reviews": rows,
        "review_count": len(rows),
        "timezone_name": timezone_name,
    }
