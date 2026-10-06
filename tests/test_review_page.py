from datetime import UTC, datetime

from app.database import SessionLocal
from app.models import ReviewToken


def _order_payload():
    now = datetime.now(UTC).isoformat()
    return {
        "external_order_id": "REV-001",
        "order_type": "DINE_IN",
        "table_number": "7",
        "staff_name": "Emma",
        "ordered_at": now,
        "paid_at": now,
        "items": [{"name": "Calamari", "quantity": 1, "price": "8.50"}],
    }


def test_review_page_lists_all_reviews_with_expandable_metadata(client):
    order = client.post("/api/orders", json=_order_payload()).json()
    with SessionLocal() as db:
        token = db.query(ReviewToken).filter_by(order_id=order["id"]).one().token

    assert client.get(f"/r/{token}").status_code == 302
    matched = client.post(
        "/api/reviews/mock/customer",
        json={
            "token": token,
            "rating": 5,
            "comment": "Great calamari",
            "reviewer_display_name": "Private Reviewer",
        },
    )
    assert matched.status_code == 201

    pending = client.post(
        "/api/reviews/mock",
        json={
            "rating": 3,
            "comment": "Unscanned feedback",
            "reviewer_display_name": "Another Private Reviewer",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    assert pending.status_code == 201

    page = client.get("/reviews")
    assert page.status_code == 200
    assert "All reviews" in page.text
    assert page.text.count('class="review-record"') == 2
    assert "Great calamari" in page.text
    assert "Unscanned feedback" in page.text
    assert "#REV-001" in page.text
    assert "Order QR" in page.text
    assert "High confidence" in page.text
    assert "Pending" in page.text
    assert 'href="/reviews" aria-current="page"' in page.text
    assert "Private Reviewer" not in page.text
    assert "Another Private Reviewer" not in page.text


def test_review_page_has_an_empty_state(client):
    page = client.get("/reviews")
    assert page.status_code == 200
    assert "No reviews yet" in page.text
