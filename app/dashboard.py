from datetime import UTC, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models import (
    Business,
    GoogleReview,
    MatchStatus,
    Order,
    PosConnection,
    PosConnectionStatus,
    ReviewMatch,
    ScanEvent,
    Scanpoint,
    ScanpointStatus,
)
from app.services.orders import get_default_business
from app.services.rating_summaries import build_rating_summaries
from app.timeutils import as_utc, utc_now


def build_dashboard(
    db: Session, max_delay_minutes: int | None = None, business: Business | None = None
) -> dict:
    business = business or get_default_business(db)
    matching_window = max_delay_minutes or get_settings().max_review_delay_minutes
    today_start = datetime.combine(utc_now().date(), time.min, tzinfo=UTC)
    orders = db.scalars(
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.scans)
            .selectinload(ScanEvent.match)
            .selectinload(ReviewMatch.google_review),
        )
        .where(Order.business_id == business.id)
        .order_by(Order.ordered_at.desc())
    ).all()
    reviews = db.scalar(
        select(func.count(GoogleReview.id)).where(
            GoogleReview.business_id == business.id,
            GoogleReview.google_create_time >= today_start,
        )
    ) or 0
    scans_today = db.scalar(
        select(func.count(ScanEvent.id)).where(
            ScanEvent.business_id == business.id, ScanEvent.scanned_at >= today_start
        )
    ) or 0
    orders_today = sum(1 for order in orders if as_utc(order.ordered_at) >= today_start)
    high = db.scalar(
        select(func.count(ReviewMatch.id))
        .join(GoogleReview)
        .where(
            GoogleReview.business_id == business.id,
            ReviewMatch.match_status == MatchStatus.HIGH_CONFIDENCE,
            GoogleReview.google_create_time >= today_start,
        )
    ) or 0
    ambiguous = db.scalar(
        select(func.count(ReviewMatch.id))
        .join(GoogleReview)
        .where(
            GoogleReview.business_id == business.id,
            ReviewMatch.match_status == MatchStatus.AMBIGUOUS,
            GoogleReview.google_create_time >= today_start,
        )
    ) or 0
    matched_reviews = db.scalar(
        select(func.count(ReviewMatch.id))
        .join(GoogleReview)
        .where(
            GoogleReview.business_id == business.id,
            ReviewMatch.scan_event_id.is_not(None),
            GoogleReview.google_create_time >= today_start,
        )
    ) or 0
    active_scanpoints = db.scalar(
        select(func.count(Scanpoint.id)).where(
            Scanpoint.business_id == business.id,
            Scanpoint.status == ScanpointStatus.ACTIVE,
        )
    ) or 0
    awaiting_pos = db.scalar(
        select(func.count(ScanEvent.id)).where(
            ScanEvent.business_id == business.id,
            ScanEvent.scanpoint_id.is_not(None),
            ScanEvent.order_id.is_(None),
        )
    ) or 0
    healthy_pos = db.scalar(
        select(func.count(PosConnection.id)).where(
            PosConnection.business_id == business.id,
            PosConnection.status == PosConnectionStatus.ACTIVE,
        )
    ) or 0

    rows = []
    for order in orders:
        scans = sorted(order.scans, key=lambda scan: as_utc(scan.scanned_at), reverse=True)
        matched_scan = next((scan for scan in scans if scan.match), None)
        display_scan = matched_scan or (scans[0] if scans else None)
        rows.append(
            {
                "order": order,
                "scan": display_scan,
                "match": display_scan.match if display_scan else None,
                "review": display_scan.match.google_review if display_scan and display_scan.match else None,
            }
        )

    rating_summaries = build_rating_summaries(db, business.id, matching_window)

    return {
        "business": business,
        "rows": rows,
        "item_ratings": rating_summaries.items,
        "worker_ratings": rating_summaries.workers,
        "metrics": {
            "orders": orders_today,
            "scans": scans_today,
            "reviews": reviews,
            "high": high,
            "ambiguous": ambiguous,
            "unmatched_scans": max(scans_today - matched_reviews, 0),
            "scan_rate": round((scans_today / orders_today * 100), 1) if orders_today else 0,
            "estimated_conversion": round((matched_reviews / scans_today * 100), 1) if scans_today else 0,
            "active_scanpoints": active_scanpoints,
            "awaiting_pos": awaiting_pos,
            "healthy_pos": healthy_pos,
        },
    }
