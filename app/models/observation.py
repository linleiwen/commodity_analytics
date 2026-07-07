"""Price Observation model (spec 7.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import util
from app.models import ConfidenceLevel, confidence_score


class PriceObservation(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    observation_id: str = Field(default_factory=lambda: util.new_id("obs"))
    run_id: str = ""
    product_id: str = ""
    source_name: str = ""
    source_type: str = "api"  # api | manual | browser | third_party
    source_url: str = ""
    source_snapshot_path: str = ""
    observed_at: str = ""
    country: str = ""  # JP | US
    platform: str = ""
    listing_title: str = ""
    listing_id: str = ""
    seller_name_hash: str | None = None
    condition: str = ""
    currency: str = ""
    price: float | None = None
    shipping_price: float | None = None
    sales_tax_included_flag: bool | None = None
    tax_free_eligible_flag: bool | None = None
    availability_status: str = ""
    quantity_available: int | None = None
    rating: float | None = None
    review_count: int | None = None
    expiration_date_text: str = ""
    expiration_date_parsed: str = ""
    price_usd: float | None = None
    match_confidence: float | None = None
    confidence_level: str = ConfidenceLevel.MISSING.value
    raw_payload_path: str = ""

    def to_row(self) -> dict[str, Any]:
        row = self.model_dump()
        row["confidence_score"] = confidence_score(self.confidence_level)
        for flag in ("sales_tax_included_flag", "tax_free_eligible_flag"):
            v = row.get(flag)
            row[flag] = None if v is None else int(bool(v))
        return row
