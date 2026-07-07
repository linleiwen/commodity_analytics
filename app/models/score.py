"""Compliance Review (7.4) and Score (7.5) models."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import util
from app.models import Compliance, PriorityTier


class ComplianceReview(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    review_id: str = Field(default_factory=lambda: util.new_id("cmp"))
    run_id: str = ""
    product_id: str = ""
    category_risk: str = Compliance.GREEN.value
    import_risk: str = Compliance.GREEN.value
    platform_risk_ebay: str = Compliance.GREEN.value
    platform_risk_facebook: str = Compliance.GREEN.value
    platform_risk_nextdoor: str = Compliance.GREEN.value
    platform_risk_xhs: str = Compliance.GREEN.value
    labeling_risk: str = Compliance.GREEN.value
    food_safety_risk: str = Compliance.GREEN.value
    cosmetic_drug_risk: str = Compliance.GREEN.value
    shipping_risk: str = Compliance.GREEN.value
    food_class: str = ""
    compliance_status: str = Compliance.GREEN.value
    reason_codes: list[str] = Field(default_factory=list)
    manual_reviewer: str = ""
    review_status: str = "auto"  # auto | needs_review | verified | blocked
    review_notes: str = ""

    def to_row(self) -> dict[str, Any]:
        row = self.model_dump()
        row["reason_codes_json"] = json.dumps(self.reason_codes, ensure_ascii=False)
        row.pop("reason_codes", None)
        return row


class Score(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    score_id: str = Field(default_factory=lambda: util.new_id("scr"))
    run_id: str = ""
    product_id: str = ""

    jp_cost_usd: float | None = None
    us_expected_sold_price_usd: float | None = None
    us_expected_net_price_usd: float | None = None
    expected_net_profit_usd: float | None = None
    profit_margin_pct: float | None = None
    profit_per_liter: float | None = None
    profit_per_lb: float | None = None

    price_gap_score: float = 0.0
    profit_density_score: float = 0.0
    absolute_profit_score: float = 0.0
    demand_heat_score: float = 0.0
    sell_through_score: float = 0.0
    shelf_life_score: float = 0.0
    shelf_life_days_remaining: float | None = None
    supply_reliability_score: float = 0.0
    ops_ease_score: float = 0.0
    strategic_fit_score: float = 0.0

    base_score: float = 0.0
    compliance_penalty: float = 0.0
    temperature_damage_penalty: float = 0.0
    fragility_penalty: float = 0.0
    matching_confidence_penalty: float = 0.0
    data_missing_penalty: float = 0.0
    final_score: float = 0.0

    recommended_qty: int = 0
    recommended_channel: str = ""
    priority_tier: str = PriorityTier.WATCHLIST.value
    estimated_total_profit: float = 0.0
    volume_used_liter: float = 0.0
    weight_used_lb: float = 0.0
    packing_notes: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    data_confidence: float = 0.0

    def to_row(self) -> dict[str, Any]:
        row = self.model_dump()
        row["reason_codes_json"] = json.dumps(self.reason_codes, ensure_ascii=False)
        row.pop("reason_codes", None)
        return row
