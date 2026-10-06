"""Regression coverage added during portfolio preparation on 6 October 2026."""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.auth import hash_api_key
from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import AttributionAudit, Business, GoogleReview, Order, OrderItem, ReviewToken
from app.services.matching import _time_score, run_matching
from test_end_to_end import order_payload
from test_matching import add_review, add_scan


@pytest.mark.parametrize("window_seconds", [60, 120, 600, 1800, 3600])
def test_time_confidence_is_monotonic_and_respects_configured_window(window_seconds):
    scores = [_time_score(delay, window_seconds) for delay in range(window_seconds + 1)]
    assert scores[0] == pytest.approx(0.99)
    assert scores[-1] == pytest.approx(0.30)
    assert all(left >= right for left, right in zip(scores, scores[1:]))
    assert _time_score(window_seconds + 1, window_seconds) == 0
    assert _time_score(-1, window_seconds) == 0


def test_identical_timestamps_have_stable_attribution_and_preserve_audits(client):
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    with SessionLocal() as db:
        business = db.scalar(select(Business))
        first = add_scan(db, business, now, "TIE-A")
        second = add_scan(db, business, now, "TIE-B")
        add_review(db, business, now + timedelta(seconds=30), "TIE-R1")
        add_review(db, business, now + timedelta(seconds=30), "TIE-R2")
        db.commit()
        previous = [(m.google_review_id, m.scan_event_id) for m in run_matching(db, business.id, 60)]
        current = [(m.google_review_id, m.scan_event_id) for m in run_matching(db, business.id, 60)]
        assert current == previous
        assert [scan for _, scan in current] == [first.id, second.id]
        assert db.scalar(select(text("count(*)")).select_from(AttributionAudit)) == 4


def test_matching_includes_window_boundary_but_excludes_earlier_scans(client):
    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    with SessionLocal() as db:
        business = db.scalar(select(Business))
        boundary = add_scan(db, business, now - timedelta(minutes=1), "BOUNDARY")
        add_scan(db, business, now - timedelta(seconds=61), "TOO-OLD")
        add_review(db, business, now)
        db.commit()
        match = run_matching(db, business.id, 1)[0]
        assert match.scan_event_id == boundary.id
        assert match.candidate_count == 1
        assert match.confidence_score == Decimal("0.3000")
        assert match.match_status == "AMBIGUOUS"


def test_disabled_scanpoint_revokes_already_opened_mock_form_and_submission(client):
    point = client.post("/api/scanpoints", json={"serial_number": "REVOKE", "label": "Seven", "table_ref": "7"}).json()
    token = point["public_id"]
    assert client.get(f"/s/{token}").status_code == 302
    assert client.get(f"/mock-google/review/{token}").status_code == 200
    client.post(f"/api/scanpoints/{point['id']}/disable")
    assert client.get(f"/mock-google/review/{token}").status_code == 410
    assert client.post("/api/reviews/mock/customer", json={"token": token, "rating": 5}).status_code == 410
    assert client.get("/api/reviews").json() == []


def test_unassigned_scanpoint_cannot_bypass_public_scan_validation(client):
    point = client.post("/api/scanpoints", json={"serial_number": "UNASSIGNED", "label": "Pending"}).json()
    token = point["public_id"]
    assert client.get(f"/s/{token}").status_code == 410
    assert client.get(f"/mock-google/review/{token}").status_code == 410
    assert client.post("/api/reviews/mock/customer", json={"token": token, "rating": 5}).status_code == 410


def test_expired_order_link_is_rejected_through_all_public_entry_points(client):
    order = client.post("/api/orders", json=order_payload()).json()
    with SessionLocal() as db:
        link = db.scalar(select(ReviewToken).where(ReviewToken.order_id == order["id"]))
        link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        token = link.token
        db.commit()
    assert client.get(f"/r/{token}").status_code == 410
    assert client.get(f"/mock-google/review/{token}").status_code == 410
    assert client.post("/api/reviews/mock/customer", json={"token": token, "rating": 5}).status_code == 410
    assert client.get("/api/scans").json() == []


@pytest.mark.parametrize("kind", ["order_id", "item_name", "serial_number", "table_ref"])
def test_whitespace_only_identifiers_are_rejected_without_creating_rows(client, kind):
    if kind in {"order_id", "item_name"}:
        data = order_payload()
        if kind == "order_id":
            data["external_order_id"] = "   "
        else:
            data["items"][0]["name"] = "   "
        response = client.post("/api/orders", json=data)
        assert client.get("/api/orders").json() == []
    else:
        data = {"serial_number": "VALID", "label": "Valid", "table_ref": "7"}
        data[kind] = "   "
        response = client.post("/api/scanpoints", json=data)
        assert client.get("/api/scanpoints").json() == []
    assert response.status_code == 422


def test_payment_before_order_is_rejected(client):
    data = order_payload()
    data["paid_at"] = (datetime.fromisoformat(data["ordered_at"]) - timedelta(minutes=1)).isoformat()
    assert client.post("/api/pos/orders", json=data).status_code == 422
    assert client.get("/api/orders").json() == []


def test_sqlite_foreign_keys_reject_orphan_items(client):
    with SessionLocal() as db:
        assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
        db.add(OrderItem(order_id=99999, name="Orphan", quantity=1, price=Decimal("1")))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.scalar(select(OrderItem)) is None


def test_request_logs_omit_tokens_query_strings_and_review_text(client, caplog):
    order = client.post("/api/orders", json=order_payload()).json()
    with SessionLocal() as db:
        token = db.scalar(select(ReviewToken.token).where(ReviewToken.order_id == order["id"]))
    with caplog.at_level(logging.INFO, logger="reviewstats.requests"):
        response = client.get(f"/r/{token}?secret=private-query")
        client.post("/api/reviews/mock/customer", json={"token": token, "rating": 5, "comment": "private-review-text"})
    assert response.headers["x-request-id"]
    assert "route=/r/{token}" in caplog.text
    assert "status=302" in caplog.text
    assert token not in caplog.text
    assert "private-query" not in caplog.text
    assert "private-review-text" not in caplog.text


def test_tenant_key_cannot_read_another_business_order_or_attribution(client, monkeypatch):
    original = client.post("/api/orders", json=order_payload()).json()
    review = client.post("/api/reviews/mock", json={"rating": 5, "created_at": datetime.now(UTC).isoformat()}).json()
    with SessionLocal() as db:
        first = db.scalar(select(Business))
        first.api_key_hash = hash_api_key("first-key")
        db.add(Business(name="Second", google_review_url="https://example.com", api_key_hash=hash_api_key("second-key")))
        db.commit()
    settings = get_settings()
    monkeypatch.setattr(settings, "require_tenant_auth", True)
    monkeypatch.setattr(settings, "tenant_api_key", None)
    headers = {"X-Tenant-Key": "second-key"}
    assert client.get(f"/api/orders/{original['id']}", headers=headers).status_code == 404
    assert client.get(f"/api/reviews/{review['id']}/attribution", headers=headers).status_code == 404
    assert client.get("/api/dashboard", headers=headers).json()["orders"] == []


def test_readiness_returns_503_when_database_query_fails(client, monkeypatch):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200

    def unavailable():
        raise RuntimeError("private-connection-string")

    monkeypatch.setattr(engine, "connect", unavailable)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "private-connection-string" not in response.text


def test_unresolved_scan_does_not_crash_or_make_ambiguity_group_eligible(client):
    from app.models import MatchStatus, ScanEvent
    from app.services.rating_summaries import build_rating_summaries
    from test_rating_summaries import add_order, add_review_with_match

    now = datetime(2026, 8, 30, 12, tzinfo=UTC)
    with SessionLocal() as db:
        business = db.scalar(select(Business))
        first, scan_a = add_order(db, business, "GRAPH-A", now, "Alice", [("Soup", 1)])
        second, scan_b = add_order(db, business, "GRAPH-B", now, "Bob", [("Salad", 1)])
        add_review_with_match(db, business, "GRAPH-R1", now + timedelta(seconds=30), 5, MatchStatus.AMBIGUOUS, first, scan_a)
        add_review_with_match(db, business, "GRAPH-R2", now + timedelta(seconds=40), 5, MatchStatus.AMBIGUOUS, second, scan_b)
        db.add(ScanEvent(business_id=business.id, scanned_at=now, redirected_at=now))
        db.commit()
        result = build_rating_summaries(db, business.id, 60)
        assert result.items == []
        assert result.workers == []


def test_order_total_overflow_is_rejected_before_sqlite_write(client):
    data = order_payload()
    data["items"] = [{"name": "Large", "price": "99999999.99", "quantity": 100}]
    assert client.post("/api/orders", json=data).status_code == 422
    assert client.get("/api/orders").json() == []
