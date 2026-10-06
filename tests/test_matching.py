from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models import Business, GoogleReview, MatchStatus, Order, OrderType, ReviewToken, ScanEvent
from app.services.matching import run_matching


def add_scan(db, business, when, external_id):
    order = Order(
        external_order_id=external_id,
        business_id=business.id,
        order_type=OrderType.TAKEAWAY,
        total=Decimal("10.00"),
        ordered_at=when,
    )
    order.review_token = ReviewToken(token=f"secure-token-{external_id}-abcdefghijklmnopqrstuvwxyz")
    db.add(order)
    db.flush()
    scan = ScanEvent(
        review_token_id=order.review_token.id,
        order_id=order.id,
        business_id=business.id,
        scanned_at=when,
        redirected_at=when,
    )
    db.add(scan)
    db.flush()
    return scan


def add_review(db, business, when, review_id="review-1"):
    review = GoogleReview(
        business_id=business.id,
        google_review_id=review_id,
        rating=5,
        comment="Good",
        google_create_time=when,
        google_update_time=when,
        retrieved_at=when,
    )
    db.add(review)
    db.flush()
    return review


def test_single_close_scan_is_high_confidence(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        scan = add_scan(db, business, now, "A")
        add_review(db, business, now + timedelta(seconds=110))
        db.commit()
        result = run_matching(db, business.id, 60)[0]
        assert result.scan_event_id == scan.id
        assert result.match_status == MatchStatus.HIGH_CONFIDENCE
        assert result.candidate_count == 1


def test_competing_nearby_scans_are_ambiguous(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        add_scan(db, business, now, "A")
        add_scan(db, business, now + timedelta(seconds=35), "B")
        add_scan(db, business, now + timedelta(seconds=62), "C")
        add_review(db, business, now + timedelta(seconds=112))
        db.commit()
        result = run_matching(db, business.id, 60)[0]
        assert result.match_status == MatchStatus.AMBIGUOUS
        assert result.candidate_count == 3
        assert float(result.confidence_score) < 0.7


def test_scan_after_review_is_never_matched(client):
    now = datetime.now(UTC)
    with SessionLocal() as db:
        business = db.query(Business).one()
        add_review(db, business, now)
        add_scan(db, business, now + timedelta(seconds=1), "AFTER")
        db.commit()
        result = run_matching(db, business.id, 60)[0]
        assert result.scan_event_id is None
        assert result.match_status == MatchStatus.UNMATCHED
        assert result.confidence_score == Decimal("0.0000")

