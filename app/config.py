from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ReviewStats - Review Attribution Platform"
    database_url: str = "sqlite:///./review_attribution.db"
    public_base_url: str = "http://localhost:8000"
    max_review_delay_minutes: int = Field(default=60, ge=1, le=1440)
    scan_order_grace_minutes: int = Field(default=90, ge=5, le=1440)
    require_tenant_auth: bool = False
    tenant_api_key: str | None = None
    attribution_algorithm_version: str = "v2.1-scanpoint"
    review_destination: Literal["mock", "google"] = "mock"
    default_business_name: str = "Demo Burger Bar"
    default_location_name: str = "Main location"
    default_timezone: str = "Europe/Dublin"
    default_google_review_url: str = (
        "https://search.google.com/local/writereview?placeid=YOUR_PLACE_ID"
    )
    google_access_token: str | None = None
    google_account_id: str | None = None
    google_location_id: str | None = None


@lru_cache
def get_settings() -> Settings:
    # Development reloads recreate this cache after environment configuration changes.
    return Settings()
