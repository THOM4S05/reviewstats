from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Business,
    BusinessLocation,
    Order,
    ScanEvent,
    Scanpoint,
    ScanpointAssignment,
    ScanpointStatus,
    ServiceArea,
)
from app.timeutils import as_utc, utc_now


def get_default_location(db: Session, business: Business) -> BusinessLocation:
    location = db.scalar(
        select(BusinessLocation)
        .where(BusinessLocation.business_id == business.id, BusinessLocation.is_active.is_(True))
        .order_by(BusinessLocation.id)
    )
    if location is None:
        settings = get_settings()
        location = BusinessLocation(
            business_id=business.id,
            name=settings.default_location_name,
            external_ref="main",
            timezone=settings.default_timezone,
            google_review_url=business.google_review_url,
        )
        db.add(location)
        db.flush()
    return location


def get_or_create_service_area(
    db: Session, business: Business, location: BusinessLocation, external_ref: str, label: str | None = None
) -> ServiceArea:
    normalized = external_ref.strip()
    area = db.scalar(
        select(ServiceArea).where(
            ServiceArea.location_id == location.id,
            ServiceArea.external_ref == normalized,
        )
    )
    if area is None:
        area = ServiceArea(
            business_id=business.id,
            location_id=location.id,
            external_ref=normalized,
            label=(label or f"Table {normalized}").strip(),
        )
        db.add(area)
        db.flush()
    return area


def active_assignment_at(
    db: Session, scanpoint_id: int, when: datetime
) -> ScanpointAssignment | None:
    assignments = db.scalars(
        select(ScanpointAssignment)
        .where(ScanpointAssignment.scanpoint_id == scanpoint_id)
        .order_by(ScanpointAssignment.starts_at.desc(), ScanpointAssignment.id.desc())
    ).all()
    moment = as_utc(when)
    return next(
        (
            assignment
            for assignment in assignments
            if as_utc(assignment.starts_at) <= moment
            and (assignment.ends_at is None or moment < as_utc(assignment.ends_at))
        ),
        None,
    )


def assign_scanpoint(
    db: Session, scanpoint: Scanpoint, area: ServiceArea, starts_at: datetime | None = None
) -> ScanpointAssignment:
    now = starts_at or utc_now()
    for assignment in db.scalars(
        select(ScanpointAssignment).where(
            ScanpointAssignment.scanpoint_id == scanpoint.id,
            ScanpointAssignment.ends_at.is_(None),
        )
    ).all():
        assignment.ends_at = now
    assignment = ScanpointAssignment(
        scanpoint_id=scanpoint.id,
        service_area_id=area.id,
        starts_at=now,
    )
    scanpoint.location_id = area.location_id
    scanpoint.status = ScanpointStatus.ACTIVE
    scanpoint.disabled_at = None
    db.add(assignment)
    db.flush()
    return assignment


def provision_scanpoint(
    db: Session,
    business: Business,
    serial_number: str,
    label: str,
    table_ref: str | None = None,
) -> Scanpoint:
    location = get_default_location(db, business)
    scanpoint = Scanpoint(
        public_id=secrets.token_urlsafe(24),
        serial_number=serial_number.strip(),
        label=label.strip(),
        business_id=business.id,
        location_id=location.id,
    )
    db.add(scanpoint)
    db.flush()
    if table_ref:
        area = get_or_create_service_area(db, business, location, table_ref)
        assign_scanpoint(db, scanpoint, area)
    db.commit()
    db.refresh(scanpoint)
    return scanpoint


def find_order_for_scan(
    db: Session, assignment: ScanpointAssignment, scanned_at: datetime
) -> Order | None:
    grace = timedelta(minutes=get_settings().scan_order_grace_minutes)
    orders = db.scalars(
        select(Order)
        .where(Order.service_area_id == assignment.service_area_id)
        .order_by(Order.ordered_at.desc())
    ).all()
    moment = as_utc(scanned_at)
    candidates = []
    for order in orders:
        opened = as_utc(order.ordered_at)
        anchor = as_utc(order.paid_at) if order.paid_at else opened
        if opened <= moment <= anchor + grace:
            candidates.append((abs((moment - anchor).total_seconds()), order))
    return min(candidates, key=lambda item: (item[0], item[1].id))[1] if candidates else None


def resolve_scan_context(
    db: Session, scanpoint: Scanpoint, scanned_at: datetime
) -> tuple[ScanpointAssignment | None, Order | None, str]:
    assignment = active_assignment_at(db, scanpoint.id, scanned_at)
    if assignment is None:
        return None, None, "No active table assignment at scan time"
    order = find_order_for_scan(db, assignment, scanned_at)
    if order is None:
        return assignment, None, "Table resolved; awaiting a compatible POS order"
    return assignment, order, "Resolved from scanpoint assignment and POS order time window"


def reconcile_unlinked_scans(db: Session, order: Order) -> int:
    if order.service_area_id is None:
        return 0
    assignments = db.scalars(
        select(ScanpointAssignment).where(
            ScanpointAssignment.service_area_id == order.service_area_id
        )
    ).all()
    assignment_ids = [assignment.id for assignment in assignments]
    if not assignment_ids:
        return 0
    scans = db.scalars(
        select(ScanEvent).where(
            ScanEvent.assignment_id.in_(assignment_ids),
            ScanEvent.order_id.is_(None),
        )
    ).all()
    linked = 0
    for scan in scans:
        active = active_assignment_at(db, scan.scanpoint_id, scan.scanned_at) if scan.scanpoint_id else None
        resolved = find_order_for_scan(db, active, scan.scanned_at) if active else None
        if resolved and resolved.id == order.id:
            scan.order_id = order.id
            scan.table_session_id = order.table_session_id
            scan.resolution_reason = "Linked after delayed POS order ingestion"
            linked += 1
    return linked
