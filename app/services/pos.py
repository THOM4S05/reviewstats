from __future__ import annotations

import secrets
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Business,
    Order,
    OrderItem,
    PosConnection,
    PosConnectionStatus,
    ReviewToken,
    SessionStatus,
    TableSession,
)
from app.schemas import PosOrderUpsert
from app.services.scanpoints import (
    get_default_location,
    get_or_create_service_area,
    reconcile_unlinked_scans,
)
from app.timeutils import as_utc, utc_now


def _connection(db: Session, business: Business, data: PosOrderUpsert) -> PosConnection:
    location = get_default_location(db, business)
    connection = db.scalar(
        select(PosConnection).where(
            PosConnection.business_id == business.id,
            PosConnection.provider == data.provider.upper(),
            PosConnection.external_location_id == data.external_location_id,
        )
    )
    if connection is None:
        connection = PosConnection(
            business_id=business.id,
            location_id=location.id,
            provider=data.provider.upper(),
            external_location_id=data.external_location_id,
            status=PosConnectionStatus.ACTIVE,
        )
        db.add(connection)
        db.flush()
    connection.status = PosConnectionStatus.ACTIVE
    connection.last_synced_at = utc_now()
    return connection


def _session_for_order(db: Session, business: Business, data: PosOrderUpsert) -> TableSession | None:
    if not data.table_number:
        return None
    location = get_default_location(db, business)
    area = get_or_create_service_area(db, business, location, data.table_number)
    external_session_id = data.external_session_id or f"order:{data.external_order_id}"
    session = db.scalar(
        select(TableSession).where(
            TableSession.business_id == business.id,
            TableSession.external_session_id == external_session_id,
        )
    )
    if session is None:
        session = TableSession(
            business_id=business.id,
            location_id=location.id,
            service_area_id=area.id,
            external_session_id=external_session_id,
            opened_at=data.ordered_at,
        )
        db.add(session)
        db.flush()
    session.opened_at = min(as_utc(session.opened_at), as_utc(data.ordered_at))
    if data.paid_at:
        session.closed_at = data.paid_at
        session.status = SessionStatus.CLOSED
    else:
        session.status = SessionStatus.OPEN
    return session


def upsert_pos_order(db: Session, business: Business, data: PosOrderUpsert) -> tuple[Order, bool, int]:
    existing = db.scalar(
        select(Order).where(
            Order.business_id == business.id,
            Order.external_order_id == data.external_order_id,
        )
    )
    if (
        existing
        and existing.source_updated_at
        and data.source_updated_at
        and as_utc(data.source_updated_at) < as_utc(existing.source_updated_at)
    ):
        return existing, False, 0

    connection = _connection(db, business, data)
    table_session = _session_for_order(db, business, data)
    location = get_default_location(db, business)
    area_id = table_session.service_area_id if table_session else None
    total = sum((item.price * item.quantity for item in data.items), Decimal("0.00"))
    created = existing is None
    if existing is None:
        existing = Order(
            external_order_id=data.external_order_id,
            business_id=business.id,
            review_token=ReviewToken(token=secrets.token_urlsafe(32)),
        )
        db.add(existing)
    existing.location_id = location.id
    existing.service_area_id = area_id
    existing.table_session_id = table_session.id if table_session else None
    existing.pos_connection_id = connection.id
    existing.order_type = data.order_type
    existing.table_number = data.table_number
    existing.staff_name = data.staff_name.strip() if data.staff_name else None
    existing.total = total
    existing.ordered_at = data.ordered_at
    existing.paid_at = data.paid_at
    existing.status = data.status.upper()
    existing.source_updated_at = data.source_updated_at or utc_now()
    existing.items = [
        OrderItem(name=item.name.strip(), quantity=item.quantity, price=item.price)
        for item in data.items
    ]
    db.flush()
    linked = reconcile_unlinked_scans(db, existing)
    db.commit()
    db.refresh(existing)
    return existing, created, linked
