from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ReviewLinkExpired, ReviewLinkNotFound, ScanpointUnassigned
from app.models import Business, Order, ReviewToken, Scanpoint, ScanpointStatus
from app.services.scanpoints import active_assignment_at
from app.timeutils import as_utc, utc_now


def business_for_mock_review(db: Session, token: str) -> Business:
    """Validate a demo link without using its identity as matching evidence."""
    review_token = db.scalar(
        select(ReviewToken)
        .options(selectinload(ReviewToken.order).selectinload(Order.business))
        .where(ReviewToken.token == token)
    )
    now = utc_now()
    if review_token is not None:
        if review_token.expires_at and as_utc(review_token.expires_at) <= now:
            raise ReviewLinkExpired("Review link has expired")
        return review_token.order.business

    scanpoint = db.scalar(select(Scanpoint).where(Scanpoint.public_id == token))
    if scanpoint is None:
        raise ReviewLinkNotFound("Review link not found")
    if scanpoint.status != ScanpointStatus.ACTIVE:
        raise ReviewLinkExpired("Scanpoint is not active")
    if active_assignment_at(db, scanpoint.id, now) is None:
        raise ScanpointUnassigned("Scanpoint has no active table assignment")
    business = db.get(Business, scanpoint.business_id)
    if business is None:
        raise ReviewLinkNotFound("Business not found")
    return business
