"""Social / Demand Signal model (spec 7.3), including sell-through metrics."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import util
from app.models import ConfidenceLevel, confidence_score


class DemandSignal(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    signal_id: str = Field(default_factory=lambda: util.new_id("sig"))
    run_id: str = ""
    product_id: str = ""
    source_name: str = ""
    query: str = ""
    source_url: str = ""
    observed_at: str = ""
    window_days: int | None = None

    mention_count: int | None = None
    post_count: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    save_count: int | None = None
    comment_count: int | None = None
    share_count: int | None = None
    unique_author_count: int | None = None
    engagement_score: float | None = None
    trend_slope: float | None = None
    sentiment_score: float | None = None
    buyer_intent_count: int | None = None
    manual_heat_label: str = ""  # low | medium | high | viral

    # sell-through metrics (Terapeak-style)
    sold_count: int | None = None
    sell_through_pct: float | None = None
    median_sold_price: float | None = None
    avg_shipping: float | None = None
    competitor_count: int | None = None
    days_to_sell: float | None = None

    signal_kind: str = "social"  # social | sell_through | trend
    notes: str = ""
    confidence_level: str = ConfidenceLevel.SCRAPED_LOW.value

    def to_row(self) -> dict[str, Any]:
        row = self.model_dump()
        row["confidence_score"] = confidence_score(self.confidence_level)
        return row
