from app.providers.base import ImportedReview, ReviewProvider


class MockGoogleReviewProvider(ReviewProvider):
    provider_name = "MOCK_GOOGLE"

    def __init__(self, reviews: list[ImportedReview] | None = None) -> None:
        self.reviews = reviews or []

    async def get_reviews(self) -> list[ImportedReview]:
        return self.reviews
