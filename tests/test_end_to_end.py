from datetime import UTC, datetime

from app.database import SessionLocal
from app.models import ReviewToken, ScanEvent


def order_payload(order_id="TEST-001"):
    now = datetime.now(UTC).isoformat()
    return {
        "external_order_id": order_id,
        "order_type": "TAKEAWAY",
        "staff_name": "Emma",
        "ordered_at": now,
        "paid_at": now,
        "items": [
            {"name": "Double Burger", "quantity": 1, "price": "8.50"},
            {"name": "Fries", "quantity": 1, "price": "4.00"},
        ],
    }


def test_complete_mock_flow(client):
    response = client.post("/api/orders", json=order_payload())
    assert response.status_code == 201
    order = response.json()
    assert order["total"] == "12.50"

    qr = client.get(f"/api/orders/{order['id']}/qr")
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert qr.content.startswith(b"\x89PNG")

    with SessionLocal() as db:
        token = db.query(ReviewToken).filter_by(order_id=order["id"]).one()
        assert len(token.token) >= 40
        assert str(order["id"]) != token.token
        token_value = token.token

    scan = client.get(f"/r/{token_value}")
    assert scan.status_code == 302
    assert scan.headers["location"] == f"/mock-google/review/{token_value}"
    review_form = client.get(scan.headers["location"])
    assert review_form.status_code == 200
    assert "DEVELOPMENT DEMO · NOT GOOGLE" in review_form.text

    submitted = client.post(
        "/api/reviews/mock/customer",
        json={
            "token": token_value,
            "rating": 5,
            "comment": "Great burger",
            "reviewer_display_name": "Test Customer",
        },
    )
    assert submitted.status_code == 201
    assert submitted.json()["match_status"] == "HIGH_CONFIDENCE"

    reviews = client.get("/api/reviews").json()
    assert len(reviews) == 1
    assert reviews[0]["provider"] == "MOCK_GOOGLE"
    matches = client.get("/api/matches")
    match = matches.json()[0]
    assert match["order_id"] == order["id"]
    assert match["match_status"] == "HIGH_CONFIDENCE"
    assert float(match["confidence_score"]) >= 0.9

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["orders"][0]["review_id"] == reviews[0]["id"]
    assert dashboard["item_ratings"] == [
        {
            "name": "Double Burger",
            "average_rating": 5.0,
            "eligible_review_count": 1,
            "rating_counts": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
        },
        {
            "name": "Fries",
            "average_rating": 5.0,
            "eligible_review_count": 1,
            "rating_counts": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
        },
    ]
    assert dashboard["worker_ratings"] == [
        {
            "name": "Emma",
            "average_rating": 5.0,
            "eligible_review_count": 1,
            "rating_counts": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1},
            "rebalanced_rating": 5.0,
            "rating_adjustment": 0.0,
            "reliability": 0.1667,
        }
    ]
    rendered = client.get("/")
    assert rendered.status_code == 200
    assert "ReviewStats" in rendered.text
    assert "Review statistics" in rendered.text
    assert "Likely Mock Google Review" in rendered.text
    assert rendered.text.count("data-rating-trigger") == 3
    assert 'aria-label="View rating distribution for Double Burger"' in rendered.text
    assert "chart-cue" not in rendered.text
    assert "▥ View chart" not in rendered.text
    assert 'role="dialog"' in rendered.text
    assert "data-rating-chart-accessible" in rendered.text
    assert "Rebalanced rating" in rendered.text
    assert 'data-rating-kind="worker"' in rendered.text
    assert 'data-rating-rebalanced="5.00"' in rendered.text


def test_each_visit_creates_a_scan(client):
    order = client.post("/api/orders", json=order_payload()).json()
    with SessionLocal() as db:
        token = db.query(ReviewToken).filter_by(order_id=order["id"]).one().token
    client.get(f"/r/{token}")
    client.get(f"/r/{token}")
    with SessionLocal() as db:
        assert db.query(ScanEvent).count() == 2


def test_duplicate_external_order_id_is_rejected(client):
    assert client.post("/api/orders", json=order_payload()).status_code == 201
    response = client.post("/api/orders", json=order_payload())
    assert response.status_code == 409


def test_customer_review_rejects_unknown_token(client):
    response = client.post(
        "/api/reviews/mock/customer",
        json={"token": "x" * 32, "rating": 5, "comment": "No order"},
    )
    assert response.status_code == 404
