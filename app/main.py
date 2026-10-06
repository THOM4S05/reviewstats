from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import router as api_router
from app.auth import require_business
from app.config import get_settings
from app.dashboard import build_dashboard
from app.database import Base, SessionLocal, engine, get_db
from app.errors import ReviewLinkError, ReviewLinkNotFound, ScanpointUnassigned
from app.models import Business, BusinessLocation, Order, Organization
from app.observability import install_request_logging
from app.services.review_catalog import build_review_catalog
from app.services.review_links import business_for_mock_review

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def seed_business() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        business = db.scalar(select(Business).limit(1))
        if business is None:
            organization = Organization(name=settings.default_business_name, slug="demo-restaurant")
            db.add(organization)
            db.flush()
            business = Business(
                organization_id=organization.id,
                name=settings.default_business_name,
                google_review_url=settings.default_google_review_url,
                google_account_id=settings.google_account_id,
                google_location_id=settings.google_location_id,
            )
            db.add(business)
            db.flush()
        elif business.organization_id is None:
            organization = Organization(name=business.name, slug=f"business-{business.id}")
            db.add(organization)
            db.flush()
            business.organization_id = organization.id
        if db.scalar(select(BusinessLocation).where(BusinessLocation.business_id == business.id)) is None:
            db.add(BusinessLocation(
                business_id=business.id,
                name=settings.default_location_name,
                external_ref="main",
                timezone=settings.default_timezone,
                google_review_url=business.google_review_url,
            ))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Keeps a fresh clone runnable; Alembic remains the schema-change mechanism.
    Base.metadata.create_all(bind=engine)
    seed_business()
    yield


app = FastAPI(title=get_settings().app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(api_router)
install_request_logging(app)


@app.exception_handler(ReviewLinkError)
async def invalid_review_link(request: Request, exc: ReviewLinkError) -> JSONResponse:
    status = 404 if isinstance(exc, ReviewLinkNotFound) else 409 if isinstance(exc, ScanpointUnassigned) else 410
    return JSONResponse({"detail": str(exc)}, status_code=status)


@app.exception_handler(IntegrityError)
async def database_conflict(request: Request, exc: IntegrityError) -> JSONResponse:
    # Do not expose SQL parameters or connection details to callers.
    return JSONResponse({"detail": "The request conflicts with existing data"}, status_code=409)


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def health_ready() -> JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM businesses LIMIT 1"))
    except Exception as exc:
        import logging
        logging.getLogger("reviewstats.app").warning("readiness_failed error_type=%s", type(exc).__name__)
        return JSONResponse({"status": "not_ready"}, status_code=503)
    return JSONResponse({"status": "ready"})


@app.get("/", response_class=HTMLResponse)
def dashboard_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={**build_dashboard(db), "title": "Review statistics"},
    )


@app.get("/mock-pos", response_class=HTMLResponse)
def mock_pos_page(request: Request):
    return templates.TemplateResponse(request=request, name="mock_pos.html", context={"title": "Mock POS"})


@app.get("/scanpoints", response_class=HTMLResponse)
def scanpoints_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="scanpoints.html",
        context={"title": "Scanpoints"},
    )


@app.get("/reviews", response_class=HTMLResponse)
def reviews_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="reviews.html",
        context={**build_review_catalog(db), "title": "All reviews"},
    )


@app.get("/testing", response_class=HTMLResponse)
def testing_page(request: Request):
    return templates.TemplateResponse(request=request, name="testing.html", context={"title": "Testing mode"})


@app.get("/mock-google/review/{token}", response_class=HTMLResponse)
def customer_mock_review_page(token: str, request: Request, db: Session = Depends(get_db)):
    business = business_for_mock_review(db, token)
    return templates.TemplateResponse(
        request=request,
        name="customer_review.html",
        context={
            "title": "Write a mock review",
            "business": business,
            "token": token,
        },
    )


@app.get("/mock-google/thank-you", response_class=HTMLResponse)
def customer_mock_thank_you_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="customer_thank_you.html",
        context={"title": "Thanks for your mock review"},
    )


@app.get("/orders/{order_id}/qr", response_class=HTMLResponse)
def order_qr_page(order_id: int, request: Request, db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    scan_url = f"{get_settings().public_base_url.rstrip('/')}/r/{order.review_token.token}"
    return templates.TemplateResponse(
        request=request,
        name="order_qr.html",
        context={"title": f"Order {order.external_order_id}", "order": order, "scan_url": scan_url},
    )


@app.get("/api/dashboard")
def dashboard_api(
    db: Session = Depends(get_db), business: Business = Depends(require_business)
):
    data = build_dashboard(db, business=business)

    def serialize_rating_row(row):
        return {
            "name": row.name,
            "average_rating": float(row.average_rating),
            "eligible_review_count": row.eligible_review_count,
            "rating_counts": row.rating_counts,
        }

    def serialize_worker_rating_row(row):
        return {
            **serialize_rating_row(row),
            "rebalanced_rating": float(row.rebalanced_rating),
            "rating_adjustment": float(row.rating_adjustment),
            "reliability": float(row.reliability),
        }

    return {
        "metrics": data["metrics"],
        "item_ratings": [serialize_rating_row(row) for row in data["item_ratings"]],
        "worker_ratings": [serialize_worker_rating_row(row) for row in data["worker_ratings"]],
        "orders": [
            {
                "order_id": row["order"].id,
                "external_order_id": row["order"].external_order_id,
                "scan_id": row["scan"].id if row["scan"] else None,
                "review_id": row["review"].id if row["review"] else None,
                "match_status": row["match"].match_status if row["match"] else None,
                "confidence_score": row["match"].confidence_score if row["match"] else None,
            }
            for row in data["rows"]
        ],
    }
