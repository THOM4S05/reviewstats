from app.providers.google import GoogleBusinessProfileReviewProvider


def test_google_review_parser_uses_actual_v4_fields():
    parsed = GoogleBusinessProfileReviewProvider._parse(
        {
            "name": "accounts/1/locations/2/reviews/abc",
            "reviewId": "abc",
            "reviewer": {"displayName": "Sam", "isAnonymous": False},
            "starRating": "FOUR",
            "comment": "Nice place",
            "createTime": "2026-08-15T20:18:42Z",
            "updateTime": "2026-08-15T20:19:00Z",
        }
    )
    assert parsed.provider_id == "abc"
    assert parsed.rating == 4
    assert parsed.reviewer_display_name == "Sam"

