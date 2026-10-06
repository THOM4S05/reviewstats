from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business, Order
from app.schemas import OrderCreate, PosOrderUpsert
from app.services.pos import upsert_pos_order


def get_default_business(db: Session) -> Business:
    business = db.scalar(select(Business).order_by(Business.id))
    if business is None:
        raise RuntimeError("No business is configured")
    return business


def create_order(db: Session, business: Business, data: OrderCreate) -> Order:
    existing = db.scalar(
        select(Order).where(
            Order.business_id == business.id,
            Order.external_order_id == data.external_order_id,
        )
    )
    if existing:
        raise ValueError("That order ID already exists")

    canonical = PosOrderUpsert(**data.model_dump(), provider="LEGACY_MOCK", external_location_id="main")
    order, _, _ = upsert_pos_order(db, business, canonical)
    return order
