from datetime import UTC, datetime, timedelta

from app.database import SessionLocal
from app.auth import hash_api_key
from app.config import get_settings
from app.models import (
    AttributionAudit,
    AttributionCandidate,
    Business,
    Order,
    ScanEvent,
    ScanpointAssignment,
)


def pos_payload(order_id: str, table: str, ordered_at: datetime, paid_at: datetime) -> dict:
    return {
        "provider": "PILOT",
        "external_location_id": "main",
        "external_order_id": order_id,
        "external_session_id": f"visit-{order_id}",
        "order_type": "DINE_IN",
        "table_number": table,
        "staff_name": "Emma",
        "status": "COMPLETED",
        "ordered_at": ordered_at.isoformat(),
        "paid_at": paid_at.isoformat(),
        "source_updated_at": paid_at.isoformat(),
        "items": [{"name": "Burger", "quantity": 1, "price": "12.00"}],
    }


def test_persistent_scanpoint_links_delayed_pos_order_and_review(client):
    provisioned = client.post(
        "/api/scanpoints",
        json={"serial_number": "SP-0001", "label": "Table seven", "table_ref": "7"},
    )
    assert provisioned.status_code == 201
    scanpoint = provisioned.json()
    assert scanpoint["status"] == "ACTIVE"
    assert scanpoint["table_ref"] == "7"
    assert "/s/" in scanpoint["scan_url"]
    assert scanpoint["public_id"] != str(scanpoint["id"])
    assert len(scanpoint["public_id"]) >= 32

    qr = client.get(f"/api/scanpoints/{scanpoint['id']}/qr")
    assert qr.status_code == 200
    assert qr.content.startswith(b"\x89PNG")
    assert qr.headers["cache-control"] == "no-store"

    redirected = client.get(f"/s/{scanpoint['public_id']}")
    assert redirected.status_code == 302
    assert redirected.headers["location"] == f"/mock-google/review/{scanpoint['public_id']}"
    assert redirected.headers["referrer-policy"] == "no-referrer"

    scans = client.get("/api/scans").json()
    assert scans[0]["scanpoint_id"] == scanpoint["id"]
    assert scans[0]["order_id"] is None
    assert "ip" not in scans[0]
    assert "user_agent" not in scans[0]

    paid_at = datetime.now(UTC)
    ingested = client.post(
        "/api/pos/orders",
        json=pos_payload("POS-001", "7", paid_at - timedelta(minutes=35), paid_at),
    )
    assert ingested.status_code == 200
    assert ingested.json()["created"] is True
    assert ingested.json()["linked_scans"] == 1
    order_id = ingested.json()["order"]["id"]

    submitted = client.post(
        "/api/reviews/mock/customer",
        json={"token": scanpoint["public_id"], "rating": 5, "comment": "Excellent"},
    )
    assert submitted.status_code == 201
    assert submitted.json()["match_status"] == "HIGH_CONFIDENCE"
    review_id = client.get("/api/reviews").json()[0]["id"]
    evidence = client.get(f"/api/reviews/{review_id}/attribution")
    assert evidence.status_code == 200
    assert evidence.json()["current"]["order_id"] == order_id
    assert evidence.json()["candidates"][0]["selected"] is True
    assert "Probabilistic" in evidence.json()["disclaimer"]

    with SessionLocal() as db:
        scan = db.query(ScanEvent).one()
        assert scan.order_id == order_id
        assert scan.table_session_id is not None
        assert "delayed POS" in scan.resolution_reason
        assert db.query(AttributionCandidate).count() == 1
        audit = db.query(AttributionAudit).one()
        assert audit.order_id == order_id
        assert "probabilistic" in audit.explanation


def test_pos_upsert_is_idempotent_and_rejects_stale_state(client):
    now = datetime.now(UTC)
    first = pos_payload("POS-002", "2", now - timedelta(hours=1), now)
    response = client.post("/api/pos/orders", json=first)
    assert response.json()["created"] is True
    order_id = response.json()["order"]["id"]

    updated = {**first, "status": "REFUNDED", "source_updated_at": (now + timedelta(minutes=1)).isoformat()}
    response = client.post("/api/pos/orders", json=updated)
    assert response.json()["created"] is False
    assert response.json()["order"]["id"] == order_id
    assert response.json()["order"]["status"] == "REFUNDED"

    stale = {**first, "status": "COMPLETED", "source_updated_at": (now - timedelta(minutes=1)).isoformat()}
    response = client.post("/api/pos/orders", json=stale)
    assert response.json()["order"]["status"] == "REFUNDED"
    with SessionLocal() as db:
        assert db.query(Order).count() == 1


def test_reassignment_keeps_history_and_disable_revokes_public_url(client):
    scanpoint = client.post(
        "/api/scanpoints",
        json={"serial_number": "SP-0002", "label": "Movable", "table_ref": "1"},
    ).json()
    reassigned = client.post(
        f"/api/scanpoints/{scanpoint['id']}/assign",
        json={"table_ref": "9", "table_label": "Patio 9"},
    )
    assert reassigned.status_code == 200
    assert reassigned.json()["table_ref"] == "9"
    with SessionLocal() as db:
        history = db.query(ScanpointAssignment).order_by(ScanpointAssignment.id).all()
        assert len(history) == 2
        assert history[0].ends_at is not None
        assert history[1].ends_at is None

    disabled = client.post(f"/api/scanpoints/{scanpoint['id']}/disable")
    assert disabled.json()["status"] == "DISABLED"
    assert client.get(f"/s/{scanpoint['public_id']}").status_code == 410


def test_management_and_pos_apis_can_require_tenant_key(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "require_tenant_auth", True)
    monkeypatch.setattr(settings, "tenant_api_key", None)
    with SessionLocal() as db:
        business = db.query(Business).one()
        business.api_key_hash = hash_api_key("pilot-secret")
        db.commit()

    assert client.get("/api/scanpoints").status_code == 401
    assert client.get("/api/scanpoints", headers={"X-Tenant-Key": "wrong"}).status_code == 401
    allowed = client.get("/api/scanpoints", headers={"X-Tenant-Key": "pilot-secret"})
    assert allowed.status_code == 200
