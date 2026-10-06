import json
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.auth import require_business
from app.config import Settings, get_settings
from app.database import get_db
from app.models import (
    AttributionAudit,
    AttributionCandidate,
    Business,
    BusinessLocation,
    GoogleReview,
    Order,
    ReviewMatch,
    ReviewToken,
    ScanEvent,
    Scanpoint,
    ScanpointAssignment,
    ScanpointStatus,
    ServiceArea,
)
from app.providers import (
    GoogleBusinessProfileReviewProvider,
    ImportedReview,
    MockGoogleReviewProvider,
)
from app.schemas import (
    CustomerMockReviewCreate,
    MatchRead,
    MockReviewCreate,
    OrderCreate,
    OrderRead,
    PosOrderResult,
    PosOrderUpsert,
    ReviewRead,
    ScanpointAssign,
    ScanpointCreate,
    ScanpointRead,
    ScanRead,
)
from app.services.matching import run_matching
from app.services.orders import create_order
from app.services.pos import upsert_pos_order
from app.services.qr import make_qr_png
from app.services.review_links import business_for_mock_review
from app.services.reviews import import_reviews
from app.services.scanpoints import (
    active_assignment_at,
    assign_scanpoint,
    get_default_location,
    get_or_create_service_area,
    provision_scanpoint,
    resolve_scan_context,
)
from app.timeutils import as_utc, utc_now

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
TenantBusiness = Annotated[Business, Depends(require_business)]


def _order_query():
    return select(Order).options(
        selectinload(Order.items), selectinload(Order.review_token), selectinload(Order.scans)
    )


@router.post("/api/orders", response_model=OrderRead, status_code=201)
def post_order(data: OrderCreate, db: Db, business: TenantBusiness) -> Order:
    try:
        return create_order(db, business, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/orders", response_model=list[OrderRead])
def get_orders(db: Db, business: TenantBusiness) -> list[Order]:
    return list(db.scalars(_order_query().where(Order.business_id == business.id).order_by(Order.ordered_at.desc())).all())


@router.get("/api/orders/{order_id}", response_model=OrderRead)
def get_order(order_id: int, db: Db, business: TenantBusiness) -> Order:
    order = db.scalar(_order_query().where(Order.id == order_id, Order.business_id == business.id))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/api/orders/{order_id}/qr")
def get_order_qr(order_id: int, db: Db, settings: AppSettings, business: TenantBusiness) -> Response:
    order = db.scalar(_order_query().where(Order.id == order_id, Order.business_id == business.id))
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    url = f"{settings.public_base_url.rstrip('/')}/r/{order.review_token.token}"
    return Response(content=make_qr_png(url), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/r/{token}", response_class=RedirectResponse)
def scan_and_redirect(token: str, db: Db) -> RedirectResponse:
    review_token = db.scalar(
        select(ReviewToken)
        .options(selectinload(ReviewToken.order).selectinload(Order.business))
        .where(ReviewToken.token == token)
    )
    if review_token is None:
        raise HTTPException(status_code=404, detail="Review link not found")
    if review_token and review_token.expires_at and as_utc(review_token.expires_at) <= utc_now():
        raise HTTPException(status_code=410, detail="Review link has expired")

    now = utc_now()
    db.add(
        ScanEvent(
            review_token_id=review_token.id,
            order_id=review_token.order_id,
            business_id=review_token.order.business_id,
            scanned_at=now,
            redirected_at=now,
        )
    )
    db.commit()
    if get_settings().review_destination == "mock":
        # Stay on the exact host the phone successfully used for the QR request.
        destination = f"/mock-google/review/{review_token.token}"
    else:
        destination = review_token.order.business.google_review_url
    return RedirectResponse(destination, status_code=302)


@router.get("/api/scans", response_model=list[ScanRead])
def get_scans(db: Db, business: TenantBusiness) -> list[dict]:
    scans = db.scalars(
        select(ScanEvent)
        .where(ScanEvent.business_id == business.id)
        .order_by(ScanEvent.scanned_at.desc())
    ).all()
    return [
        {
            "id": s.id,
            "business_id": s.business_id,
            "scanpoint_id": s.scanpoint_id,
            "assignment_id": s.assignment_id,
            "table_session_id": s.table_session_id,
            "order_id": s.order_id,
            "scanned_at": s.scanned_at,
            "resolution_reason": s.resolution_reason,
        }
        for s in scans
    ]


def _scanpoint_payload(db: Session, scanpoint: Scanpoint, settings: Settings) -> dict:
    assignment = active_assignment_at(db, scanpoint.id, utc_now())
    area = db.get(ServiceArea, assignment.service_area_id) if assignment else None
    return {
        "id": scanpoint.id,
        "public_id": scanpoint.public_id,
        "serial_number": scanpoint.serial_number,
        "label": scanpoint.label,
        "business_id": scanpoint.business_id,
        "location_id": scanpoint.location_id,
        "status": scanpoint.status,
        "scan_url": f"{settings.public_base_url.rstrip('/')}/s/{scanpoint.public_id}",
        "table_ref": area.external_ref if area else None,
        "table_label": area.label if area else None,
    }


@router.post("/api/scanpoints", response_model=ScanpointRead, status_code=201)
def post_scanpoint(data: ScanpointCreate, db: Db, settings: AppSettings, business: TenantBusiness) -> dict:
    try:
        scanpoint = provision_scanpoint(
            db, business, data.serial_number, data.label, data.table_ref
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="That scanpoint serial number already exists") from exc
    return _scanpoint_payload(db, scanpoint, settings)


@router.get("/api/scanpoints", response_model=list[ScanpointRead])
def get_scanpoints(db: Db, settings: AppSettings, business: TenantBusiness) -> list[dict]:
    scanpoints = db.scalars(
        select(Scanpoint)
        .where(Scanpoint.business_id == business.id)
        .order_by(Scanpoint.created_at.desc())
    ).all()
    return [_scanpoint_payload(db, scanpoint, settings) for scanpoint in scanpoints]


@router.post("/api/scanpoints/{scanpoint_id}/assign", response_model=ScanpointRead)
def post_scanpoint_assignment(
    scanpoint_id: int,
    data: ScanpointAssign,
    db: Db,
    settings: AppSettings,
    business: TenantBusiness,
) -> dict:
    scanpoint = db.get(Scanpoint, scanpoint_id)
    if scanpoint is None or scanpoint.business_id != business.id:
        raise HTTPException(status_code=404, detail="Scanpoint not found")
    location = db.get(BusinessLocation, scanpoint.location_id) or get_default_location(db, business)
    area = get_or_create_service_area(db, business, location, data.table_ref, data.table_label)
    assign_scanpoint(db, scanpoint, area)
    db.commit()
    return _scanpoint_payload(db, scanpoint, settings)


@router.post("/api/scanpoints/{scanpoint_id}/disable", response_model=ScanpointRead)
def disable_scanpoint(
    scanpoint_id: int, db: Db, settings: AppSettings, business: TenantBusiness
) -> dict:
    scanpoint = db.get(Scanpoint, scanpoint_id)
    if scanpoint is None or scanpoint.business_id != business.id:
        raise HTTPException(status_code=404, detail="Scanpoint not found")
    now = utc_now()
    for assignment in db.scalars(
        select(ScanpointAssignment).where(
            ScanpointAssignment.scanpoint_id == scanpoint.id,
            ScanpointAssignment.ends_at.is_(None),
        )
    ).all():
        assignment.ends_at = now
    scanpoint.status = ScanpointStatus.DISABLED
    scanpoint.disabled_at = now
    db.commit()
    return _scanpoint_payload(db, scanpoint, settings)


@router.get("/api/scanpoints/{scanpoint_id}/qr")
def get_scanpoint_qr(
    scanpoint_id: int, db: Db, settings: AppSettings, business: TenantBusiness
) -> Response:
    scanpoint = db.get(Scanpoint, scanpoint_id)
    if scanpoint is None or scanpoint.business_id != business.id:
        raise HTTPException(status_code=404, detail="Scanpoint not found")
    url = f"{settings.public_base_url.rstrip('/')}/s/{scanpoint.public_id}"
    return Response(
        content=make_qr_png(url),
        media_type="image/png",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/s/{public_id}", response_class=RedirectResponse)
def scanpoint_redirect(public_id: str, db: Db, settings: AppSettings) -> RedirectResponse:
    scanpoint = db.scalar(select(Scanpoint).where(Scanpoint.public_id == public_id))
    if scanpoint is None:
        raise HTTPException(status_code=404, detail="Scanpoint not found")
    if scanpoint.status != ScanpointStatus.ACTIVE:
        raise HTTPException(status_code=410, detail="Scanpoint is not active")
    now = utc_now()
    assignment, order, reason = resolve_scan_context(db, scanpoint, now)
    if assignment is None:
        raise HTTPException(status_code=409, detail="Scanpoint has no active table assignment")
    scan = ScanEvent(
        scanpoint_id=scanpoint.id,
        assignment_id=assignment.id,
        table_session_id=order.table_session_id if order else None,
        order_id=order.id if order else None,
        business_id=scanpoint.business_id,
        scanned_at=now,
        redirected_at=now,
        resolution_reason=reason,
    )
    db.add(scan)
    db.commit()
    location = db.get(BusinessLocation, scanpoint.location_id)
    business = db.get(Business, scanpoint.business_id)
    destination = (
        f"/mock-google/review/{scanpoint.public_id}"
        if settings.review_destination == "mock"
        else (location.google_review_url if location and location.google_review_url else business.google_review_url)
    )
    return RedirectResponse(
        destination,
        status_code=302,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "no-referrer"},
    )


@router.post("/api/pos/orders", response_model=PosOrderResult)
def post_pos_order(data: PosOrderUpsert, db: Db, business: TenantBusiness) -> dict:
    try:
        order, created, linked_scans = upsert_pos_order(db, business, data)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="The POS order conflicts with existing data") from exc
    return {
        "created": created,
        "linked_scans": linked_scans,
        "order": OrderRead.model_validate(order),
    }


@router.get("/api/reviews/{review_id}/attribution")
def get_review_attribution(review_id: int, db: Db, business: TenantBusiness) -> dict:
    review = db.get(GoogleReview, review_id)
    if review is None or review.business_id != business.id:
        raise HTTPException(status_code=404, detail="Review not found")
    match = db.scalar(select(ReviewMatch).where(ReviewMatch.google_review_id == review.id))
    candidates = db.scalars(
        select(AttributionCandidate)
        .where(AttributionCandidate.google_review_id == review.id)
        .order_by(AttributionCandidate.rank)
    ).all()
    audits = db.scalars(
        select(AttributionAudit)
        .where(AttributionAudit.google_review_id == review.id)
        .order_by(AttributionAudit.created_at.desc(), AttributionAudit.id.desc())
    ).all()
    return {
        "review_id": review.id,
        "disclaimer": "Probabilistic attribution; Google supplies no scanpoint or order identifier.",
        "current": None if match is None else {
            "status": match.match_status,
            "confidence_score": match.confidence_score,
            "scan_event_id": match.scan_event_id,
            "order_id": match.order_id,
            "algorithm_version": match.algorithm_version,
            "explanation": json.loads(match.explanation) if match.explanation else None,
        },
        "candidates": [
            {
                "rank": candidate.rank,
                "scan_event_id": candidate.scan_event_id,
                "order_id": candidate.order_id,
                "score": candidate.score,
                "selected": candidate.selected,
                "evidence": json.loads(candidate.evidence),
            }
            for candidate in candidates
        ],
        "history": [
            {
                "status": audit.match_status,
                "confidence_score": audit.confidence_score,
                "scan_event_id": audit.scan_event_id,
                "order_id": audit.order_id,
                "algorithm_version": audit.algorithm_version,
                "created_at": audit.created_at,
                "explanation": json.loads(audit.explanation),
            }
            for audit in audits
        ],
    }


@router.get("/api/reviews", response_model=list[ReviewRead])
def get_reviews(db: Db, business: TenantBusiness) -> list[GoogleReview]:
    return list(db.scalars(
        select(GoogleReview)
        .where(GoogleReview.business_id == business.id)
        .order_by(GoogleReview.google_create_time.desc())
    ).all())


@router.post("/api/reviews/mock", response_model=ReviewRead, status_code=201)
async def post_mock_review(data: MockReviewCreate, db: Db, business: TenantBusiness) -> GoogleReview:
    provider = MockGoogleReviewProvider(
        [
            ImportedReview(
                provider_id=data.google_review_id or f"mock-{uuid4()}",
                reviewer_display_name=data.reviewer_display_name,
                rating=data.rating,
                comment=data.comment,
                create_time=data.created_at,
                update_time=data.created_at,
            )
        ]
    )
    try:
        await import_reviews(db, business.id, provider)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Review ID already exists") from exc
    review = db.scalar(
        select(GoogleReview).where(
            GoogleReview.business_id == business.id,
            GoogleReview.google_review_id == provider.reviews[0].provider_id,
        )
    )
    assert review is not None
    return review


@router.post("/api/reviews/mock/customer", status_code=201)
async def post_customer_mock_review(data: CustomerMockReviewCreate, db: Db, settings: AppSettings) -> dict:
    """Accept a review from the local QR destination using server-controlled time."""
    business = business_for_mock_review(db, data.token)

    created_at = utc_now()
    provider = MockGoogleReviewProvider(
        [
            ImportedReview(
                provider_id=f"mock-customer-{uuid4()}",
                reviewer_display_name=data.reviewer_display_name,
                rating=data.rating,
                comment=data.comment,
                create_time=created_at,
                update_time=created_at,
            )
        ]
    )
    business_id = business.id
    await import_reviews(db, business_id, provider)
    matches = run_matching(db, business_id, settings.max_review_delay_minutes)
    match = next(
        (item for item in matches if item.google_review.google_review_id == provider.reviews[0].provider_id),
        None,
    )
    return {
        "created": True,
        "match_status": match.match_status if match else None,
        "confidence_score": match.confidence_score if match else None,
        "thank_you_url": "/mock-google/thank-you",
    }


@router.post("/api/reviews/sync")
async def sync_google_reviews(db: Db, settings: AppSettings, business: TenantBusiness) -> dict:
    if not all([settings.google_access_token, settings.google_account_id, settings.google_location_id]):
        raise HTTPException(
            status_code=503,
            detail="Set GOOGLE_ACCESS_TOKEN, GOOGLE_ACCOUNT_ID and GOOGLE_LOCATION_ID first",
        )
    provider = GoogleBusinessProfileReviewProvider(
        settings.google_access_token,
        settings.google_account_id,
        settings.google_location_id,
    )
    try:
        created, updated = await import_reviews(db, business.id, provider)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Google API returned {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not reach Google Business Profile API") from exc
    return {"created": created, "updated": updated}


@router.post("/api/matching/run", response_model=list[MatchRead])
def post_matching(db: Db, settings: AppSettings, business: TenantBusiness) -> list[ReviewMatch]:
    return run_matching(db, business.id, settings.max_review_delay_minutes)


@router.get("/api/matches", response_model=list[MatchRead])
def get_matches(db: Db, business: TenantBusiness) -> list[ReviewMatch]:
    return list(db.scalars(
        select(ReviewMatch)
        .join(GoogleReview)
        .where(GoogleReview.business_id == business.id)
        .order_by(ReviewMatch.created_at.desc())
    ).all())
