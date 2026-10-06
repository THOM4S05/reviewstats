import hashlib
import hmac
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_db
from app.models import Business
from app.services.orders import get_default_business


def hash_api_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_business(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_tenant_key: Annotated[str | None, Header()] = None,
) -> Business:
    if not settings.require_tenant_auth:
        return get_default_business(db)
    supplied_hash = hash_api_key(x_tenant_key) if x_tenant_key else ""
    if supplied_hash:
        business = db.scalar(select(Business).where(Business.api_key_hash == supplied_hash))
        if business is not None:
            return business
    if settings.tenant_api_key:
        expected_hash = hash_api_key(settings.tenant_api_key)
        if hmac.compare_digest(supplied_hash, expected_hash):
            return get_default_business(db)
    raise HTTPException(status_code=401, detail="A valid X-Tenant-Key header is required")
