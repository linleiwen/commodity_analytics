"""Constrained suitcase-packing optimizer (spec section 10).

MVP greedy allocator: repeatedly add the single unit with the highest score-weighted
profit density that still fits every constraint (volume, weight, per-category volume caps,
per-SKU unit caps, distinct-SKU cap, and YELLOW-risk quantity caps). Deterministic and
explainable; can later be swapped for an ILP (e.g. OR-Tools) behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import Compliance, PriorityTier
from app.models.score import Score

_BUY_TIERS = {PriorityTier.A.value, PriorityTier.B.value, PriorityTier.C.value}
_MIN_UNIT_VOLUME = 0.05  # liter floor so tiny items don't produce runaway density


@dataclass
class Candidate:
    score: Score
    group: str
    unit_volume: float
    unit_weight_lb: float
    unit_profit: float
    is_yellow: bool
    max_units: int
    qty: int = 0

    @property
    def value_metric(self) -> float:
        return self.score.final_score * self.unit_profit / max(self.unit_volume, _MIN_UNIT_VOLUME)


@dataclass
class PlanSummary:
    total_estimated_profit: float = 0.0
    volume_used_liter: float = 0.0
    weight_used_lb: float = 0.0
    available_volume_liter: float = 0.0
    available_weight_lb: float = 0.0
    distinct_skus: int = 0
    category_volume: dict[str, float] = field(default_factory=dict)
    risk_units: dict[str, int] = field(default_factory=dict)


def _available(suitcase_cfg: dict[str, Any]) -> tuple[float, float]:
    vol = wt = 0.0
    for bag in suitcase_cfg.get("suitcases", []):
        vol += max(0.0, bag.get("usable_volume_liter", 0) - bag.get("reserved_volume_liter", 0))
        wt += max(0.0, bag.get("max_weight_lb", 0) - bag.get("reserved_weight_lb", 0))
    return vol, wt


def _packing_notes(product: dict[str, Any]) -> str:
    notes = []
    if str(product.get("melt_risk_level")).upper() == "HIGH":
        notes.append("HIGH melt risk: insulate / cold pack / avoid summer checked-bag heat")
    elif str(product.get("melt_risk_level")).upper() == "MEDIUM":
        notes.append("melt risk: keep central, away from bag exterior")
    if str(product.get("crush_risk_level")).upper() in {"MEDIUM", "HIGH"}:
        notes.append("crush risk: hard-side layer / rigid box / pad edges")
    if str(product.get("leak_risk_level")).upper() in {"MEDIUM", "HIGH"}:
        notes.append("leak risk: seal in zip bag, upright")
    if str(product.get("storage_condition")) in {"cool", "refrigerated"}:
        notes.append("temperature sensitive: minimize transit heat exposure")
    return "; ".join(notes) or "standard packing"


def optimize(
    scores: list[Score],
    products: dict[str, dict[str, Any]],
    compliance: dict[str, dict[str, Any]],
    suitcase_cfg: dict[str, Any],
) -> tuple[list[Score], PlanSummary]:
    bc = suitcase_cfg.get("business_constraints", {})
    avail_vol, avail_wt = _available(suitcase_cfg)
    max_skus = bc.get("max_skus", 40)
    default_cap = bc.get("max_units_per_sku_default", 6)
    yellow_cap = bc.get("max_units_per_yellow_risk_sku", 2)
    cat_fraction = bc.get("category_caps", {})
    diversity = bool(bc.get("diversity_bonus"))
    diversity_factor = bc.get("diversity_bonus_factor", 1.05)
    cat_cap_volume = {g: frac * avail_vol for g, frac in cat_fraction.items()}

    candidates: list[Candidate] = []
    for s in scores:
        if s.priority_tier not in _BUY_TIERS:
            continue
        if not s.expected_net_profit_usd or s.expected_net_profit_usd <= 0:
            continue
        product = products.get(s.product_id, {})
        comp = compliance.get(s.product_id, {})
        is_yellow = comp.get("compliance_status") == Compliance.YELLOW.value
        unit_vol = s.volume_used_liter or _MIN_UNIT_VOLUME
        candidates.append(
            Candidate(
                score=s,
                group=str(product.get("category_group", "non_food_gifts")),
                unit_volume=unit_vol,
                unit_weight_lb=s.weight_used_lb or 0.0,
                unit_profit=float(s.expected_net_profit_usd),
                is_yellow=is_yellow,
                max_units=yellow_cap if is_yellow else default_cap,
            )
        )

    vol_used = wt_used = 0.0
    cat_used: dict[str, float] = {}
    distinct = 0

    while True:
        best: Candidate | None = None
        best_metric = -1.0
        for c in candidates:
            if c.qty >= c.max_units:
                continue
            opening_new = c.qty == 0
            if opening_new and distinct >= max_skus:
                continue
            if vol_used + c.unit_volume > avail_vol + 1e-9:
                continue
            if wt_used + c.unit_weight_lb > avail_wt + 1e-9:
                continue
            cap = cat_cap_volume.get(c.group)
            if cap is not None and cat_used.get(c.group, 0.0) + c.unit_volume > cap + 1e-9:
                continue
            metric = c.value_metric
            if opening_new and diversity:
                metric *= diversity_factor
            if metric > best_metric:
                best_metric = metric
                best = c
        if best is None:
            break
        if best.qty == 0:
            distinct += 1
        best.qty += 1
        vol_used += best.unit_volume
        wt_used += best.unit_weight_lb
        cat_used[best.group] = cat_used.get(best.group, 0.0) + best.unit_volume

    summary = PlanSummary(
        available_volume_liter=round(avail_vol, 2),
        available_weight_lb=round(avail_wt, 2),
        category_volume={g: round(v, 2) for g, v in cat_used.items()},
    )
    risk_units = {Compliance.GREEN.value: 0, Compliance.YELLOW.value: 0}
    for c in candidates:
        s = c.score
        s.recommended_qty = c.qty
        s.estimated_total_profit = round(c.qty * c.unit_profit, 2)
        s.volume_used_liter = round(c.qty * c.unit_volume, 3)
        s.weight_used_lb = round(c.qty * c.unit_weight_lb, 3)
        s.packing_notes = _packing_notes(products.get(s.product_id, {}))
        if c.qty > 0:
            summary.total_estimated_profit += s.estimated_total_profit
            summary.volume_used_liter += s.volume_used_liter
            summary.weight_used_lb += s.weight_used_lb
            risk_units[Compliance.YELLOW.value if c.is_yellow else Compliance.GREEN.value] += c.qty

    summary.total_estimated_profit = round(summary.total_estimated_profit, 2)
    summary.volume_used_liter = round(summary.volume_used_liter, 2)
    summary.weight_used_lb = round(summary.weight_used_lb, 2)
    summary.distinct_skus = distinct
    summary.risk_units = risk_units
    return scores, summary
