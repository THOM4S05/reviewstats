from datetime import datetime

import httpx

from app.providers.base import ImportedReview, ReviewProvider

STAR_VALUES = {
    "ONE": 1,
    "TWO": 2,
    "THREE": 3,
    "FOUR": 4,
    "FIVE": 5,
}


class GoogleBusinessProfileReviewProvider(ReviewProvider):
    """Official Google Business Profile API v4 reviews client.

    The caller supplies an OAuth access token. Production refresh-token storage and
    the consent callback deliberately remain outside this MVP.
    """

    base_url = "https://mybusiness.googleapis.com/v4"
    provider_name = "GOOGLE_BUSINESS_PROFILE"

    def __init__(self, access_token: str, account_id: str, location_id: str) -> None:
        self.access_token = access_token
        self.account_id = account_id.removeprefix("accounts/")
        self.location_id = location_id.removeprefix("locations/")

    async def get_reviews(self) -> list[ImportedReview]:
        url = f"{self.base_url}/accounts/{self.account_id}/locations/{self.location_id}/reviews"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        reviews: list[ImportedReview] = []
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=20) as client:
            while True:
                params = {"pageSize": "50"}
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(url, headers=headers, params=params)
                response.raise_for_status()
                payload = response.json()
                reviews.extend(self._parse(item) for item in payload.get("reviews", []))
                page_token = payload.get("nextPageToken")
                if not page_token:
                    return reviews

    @staticmethod
    def _parse(item: dict) -> ImportedReview:
        create_time = datetime.fromisoformat(item["createTime"].replace("Z", "+00:00"))
        update_time = datetime.fromisoformat(item.get("updateTime", item["createTime"]).replace("Z", "+00:00"))
        reviewer = item.get("reviewer") or {}
        return ImportedReview(
            provider_id=item.get("reviewId") or item["name"].rsplit("/", 1)[-1],
            reviewer_display_name=reviewer.get("displayName"),
            rating=STAR_VALUES[item["starRating"]],
            comment=item.get("comment"),
            create_time=create_time,
            update_time=update_time,
        )
