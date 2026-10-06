from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GoogleReview
from app.providers.base import ReviewProvider
from app.timeutils import utc_now


async def import_reviews(db: Session, business_id: int, provider: ReviewProvider) -> tuple[int, int]:
    created = updated = 0
    for data in await provider.get_reviews():
        review = db.scalar(
            select(GoogleReview).where(
                GoogleReview.business_id == business_id,
                GoogleReview.google_review_id == data.provider_id,
            )
        )
        if review is None:
            review = GoogleReview(
                business_id=business_id,
                google_review_id=data.provider_id,
                provider=provider.provider_name,
            )
            db.add(review)
            created += 1
        else:
            updated += 1
        review.provider = provider.provider_name
        review.reviewer_display_name = data.reviewer_display_name
        review.rating = data.rating
        review.comment = data.comment
        review.google_create_time = data.create_time
        review.google_update_time = data.update_time
        review.retrieved_at = utc_now()
    db.commit()
    return created, updated
