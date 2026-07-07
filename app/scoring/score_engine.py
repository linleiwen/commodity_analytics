"""Scoring engine (spec section 9).

Two-pass design:

1. Aggregate raw per-product economics and demand metrics from observations + signals.
2. Percentile/min-max normalize across the population, apply weights and penalties,
   run hard filters, and assign a priority tier.

Returns ``Score`` models; the luggage optimizer later fills in recommended quantities.
"""

from __future__ import annotations

import json
import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from app.models import Compliance, PriorityTier, confidence_score
from app.models.score import Score
from app.normalizers import platform_fees, shelf_life, units

_HEAT_LABEL = {"low": 0.25, "medium": 0.5, "high": 0.75, "viral": 1.0}
_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


# --------------------------------------------------------------------------- helpers
def _median(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return float(s.median()) if not s.empty else None


def _sum(series: pd.Series) -> float:
    return float(pd.to_numeric(series, errors="coerce").fillna(0).sum())


def _minmax(series: pd.Series) -> pd.Series:
    """Scale to 0-1. Rows that are NaN map to 0; a flat non-zero population maps to 0.5."""
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(0.0, index=series.index)
    lo, hi = valid.min(), valid.max()
    if hi == lo:
        return s.notna().astype(float) * 0.5
    return ((s - lo) / (hi - lo)).fillna(0.0).clip(0, 1)


def _pct_rank_winsor(series: pd.Series, lo_pct: float, hi_pct: float) -> pd.Series:
    """Winsorize then percentile-rank (0-1). NaN -> 0."""
    s = pd.to_numeric(series, errors="coerce")
    valid = s.dropna()
    if valid.empty:
        return pd.Series(0.0, index=series.index)
    lo, hi = valid.quantile(lo_pct), valid.quantile(hi_pct)
    clipped = s.clip(lo, hi)
    return clipped.rank(pct=True).fillna(0.0)


# --------------------------------------------------------------------------- pass 1
def _aggregate_product(
    product: dict[str, Any],
    obs: pd.DataFrame,
    signals: pd.DataFrame,
    return_date: date,
    scoring_cfg: dict[str, Any],
) -> dict[str, Any]:
    pid = product["product_id"]
    p_obs = obs[obs["product_id"] == pid] if not obs.empty else obs
    p_sig = signals[signals["product_id"] == pid] if not signals.empty else signals

    # ---- JP acquisition cost (USD): prefer manual field-survey prices ----
    jp = p_obs[(p_obs["country"] == "JP") & p_obs["price_usd"].notna()] if not p_obs.empty else p_obs
    jp_cost = None
    if not jp.empty:
        field = jp[jp["source_type"] == "manual"]
        jp_cost = _median((field if not field.empty else jp)["price_usd"])

    # ---- US expected sold price (USD): prefer sell-through medians, else haircut listings ----
    us_price = None
    if not p_sig.empty:
        st = p_sig[(p_sig["signal_kind"] == "sell_through") & p_sig["median_sold_price"].notna()]
        if not st.empty:
            us_price = _median(st["median_sold_price"])
    if us_price is None and not p_obs.empty:
        us_obs = p_obs[(p_obs["country"] == "US") & p_obs["price_usd"].notna()]
        if not us_obs.empty:
            us_price = _median(us_obs["price_usd"])
            if us_price is not None:
                us_price *= 0.90  # active-listing prices overstate realized sale price

    # ---- volume / weight ----
    vol, wt_g, vol_estimated, wt_missing = units.resolve_volume_weight(
        volume_liter=product.get("package_volume_liter"),
        length_cm=product.get("package_length_cm"),
        width_cm=product.get("package_width_cm"),
        height_cm=product.get("package_height_cm"),
        weight_g=product.get("package_weight_g"),
        unit_size_text=product.get("unit_size_text"),
    )
    wt_lb = units.grams_to_lb(wt_g)

    # ---- net profit ----
    econ = platform_fees.compute_net_profit(
        us_sold_price_usd=us_price, jp_cost_usd=jp_cost, volume_liter=vol
    )
    net = econ["expected_net_profit_usd"]
    ppl = platform_fees.profit_density(net, vol)
    pplb = platform_fees.profit_per_lb(net, wt_lb)

    # ---- shelf life ----
    exp_dates = []
    if not p_obs.empty:
        for v in p_obs["expiration_date_parsed"].dropna().tolist():
            d = shelf_life.to_date(v)
            if d:
                exp_dates.append(d)
    days_remaining = None
    if exp_dates:
        days_remaining = shelf_life.remaining_days(min(exp_dates), return_date)
    elif product.get("default_shelf_life_days"):
        days_remaining = float(product["default_shelf_life_days"])
    sl_score, sl_hardfail = shelf_life.shelf_life_score(
        days_remaining,
        is_food=bool(product.get("is_food")),
        is_cosmetic=bool(product.get("is_cosmetic")),
        config=scoring_cfg,
    )

    # ---- demand heat (raw) ----
    mentions = engagement = buyer_intent = 0.0
    trend = 0.0
    n_sources = 0
    label_val = 0.0
    soc = p_sig[p_sig["signal_kind"].isin(["social", "trend"])] if not p_sig.empty else p_sig
    if not soc.empty:
        mentions = _sum(soc["mention_count"]) + _sum(soc["post_count"])
        eng = _sum(soc["engagement_score"])
        if eng == 0:
            eng = _sum(soc["like_count"]) + _sum(soc["save_count"]) + _sum(soc["comment_count"]) + _sum(soc["share_count"])
        engagement = eng
        buyer_intent = _sum(soc["buyer_intent_count"])
        trend = float(pd.to_numeric(soc["trend_slope"], errors="coerce").fillna(0).mean())
        n_sources = int(soc["source_name"].nunique())
        labels = soc["manual_heat_label"].dropna().astype(str).str.lower().tolist()
        label_val = max((_HEAT_LABEL.get(x, 0.0) for x in labels), default=0.0)
    heat_raw = (
        math.log1p(mentions)
        + math.log1p(engagement)
        + 0.5 * n_sources
        + 0.3 * math.log1p(buyer_intent)
        + 2.0 * label_val
        + max(0.0, trend)
    )
    has_demand = (not soc.empty) and (mentions + engagement + buyer_intent + label_val) > 0

    # ---- sell-through (raw) ----
    st_raw = 0.0
    has_sellthrough = False
    if not p_sig.empty:
        st = p_sig[p_sig["signal_kind"] == "sell_through"]
        if not st.empty:
            has_sellthrough = True
            sold = _sum(st["sold_count"])
            stp = float(pd.to_numeric(st["sell_through_pct"], errors="coerce").fillna(0).mean())
            competitors = float(pd.to_numeric(st["competitor_count"], errors="coerce").fillna(0).mean())
            days_to_sell = float(pd.to_numeric(st["days_to_sell"], errors="coerce").fillna(0).mean())
            st_raw = (
                math.log1p(sold)
                + (stp / 100.0 if stp > 1 else stp) * 2.0
                - 0.15 * math.log1p(competitors)
                - 0.02 * days_to_sell
            )

    # ---- soft heuristic scores ----
    limited = bool(product.get("limited_edition_flag"))
    supply = 0.6 + (0.0 if limited else 0.15)
    if not jp.empty and (jp["availability_status"].astype(str).str.contains("in", case=False).any()):
        supply += 0.1
    supply = min(1.0, supply)

    ops = 1.0
    for lvl in (product.get("melt_risk_level"), product.get("crush_risk_level"), product.get("leak_risk_level")):
        ops -= 0.12 * _RISK_ORDER.get(str(lvl).upper(), 0)
    if wt_lb and wt_lb > 1.5:
        ops -= 0.15
    if vol and vol > 1.5:
        ops -= 0.15
    ops = max(0.0, min(1.0, ops))

    strat = 0.55
    if str(product.get("category_group")) in {"cosmetic", "non_food_gifts"}:
        strat += 0.15
    if not limited:
        strat += 0.10
    if product.get("brand"):
        strat += 0.05
    strat = min(1.0, strat)

    # ---- data confidence ----
    conf_vals = []
    if not p_obs.empty:
        conf_vals.extend(pd.to_numeric(p_obs["confidence_score"], errors="coerce").dropna().tolist())
    if not p_sig.empty:
        conf_vals.extend(pd.to_numeric(p_sig["confidence_score"], errors="coerce").dropna().tolist())
    data_conf = float(np.mean(conf_vals)) if conf_vals else 0.2

    # ---- match confidence (max across priced observations, else manual override) ----
    match_conf = None
    if not p_obs.empty:
        mc = pd.to_numeric(p_obs["match_confidence"], errors="coerce").dropna()
        if not mc.empty:
            match_conf = float(mc.max())

    return {
        "product_id": pid,
        "jp_cost_usd": jp_cost,
        "us_expected_sold_price_usd": us_price,
        "us_expected_net_price_usd": econ["us_expected_net_price_usd"],
        "expected_net_profit_usd": net,
        "profit_margin_pct": econ["profit_margin_pct"],
        "profit_per_liter": ppl,
        "profit_per_lb": pplb,
        "volume_liter": vol,
        "weight_lb": wt_lb,
        "vol_estimated": vol_estimated,
        "weight_missing": wt_missing,
        "shelf_life_days_remaining": days_remaining,
        "shelf_life_score": sl_score,
        "shelf_life_hardfail": sl_hardfail,
        "heat_raw": heat_raw if has_demand else np.nan,
        "sell_through_raw": st_raw if has_sellthrough else np.nan,
        "supply_reliability_score": supply,
        "ops_ease_score": ops,
        "strategic_fit_score": strat,
        "data_confidence": data_conf,
        "match_confidence": match_conf,
        "has_us_sold_data": us_price is not None,
        "has_jp_price": jp_cost is not None,
    }


# --------------------------------------------------------------------------- penalties
def _matching_penalty(match_conf: float | None, pen: dict[str, Any]) -> tuple[float, bool]:
    """Return (penalty, block_flag)."""
    if match_conf is None:
        return pen.get("match_conf_070_079", 8), False
    if match_conf >= 0.90:
        return pen.get("match_conf_090_plus", 0), False
    if match_conf >= 0.80:
        return pen.get("match_conf_080_089", 3), False
    if match_conf >= 0.70:
        return pen.get("match_conf_070_079", 8), False
    return 30.0, True  # below threshold -> block unless manually verified


def _compliance_penalty(status: str, n_yellow_dims: int, pen: dict[str, Any]) -> float:
    if status == Compliance.GREEN.value:
        return 0.0
    if status == Compliance.YELLOW.value:
        lo = pen.get("compliance_yellow_min", 10)
        hi = pen.get("compliance_yellow_max", 25)
        return lo + (hi - lo) * min(1.0, n_yellow_dims / 3.0)
    return 100.0  # RED handled as block


# --------------------------------------------------------------------------- pass 2/3
def compute_scores(
    products: pd.DataFrame,
    observations: pd.DataFrame,
    signals: pd.DataFrame,
    compliance: pd.DataFrame,
    scoring_cfg: dict[str, Any],
    return_date: date,
    run_id: str,
) -> list[Score]:
    if products.empty:
        return []

    rows = [
        _aggregate_product(p, observations, signals, return_date, scoring_cfg)
        for p in products.to_dict(orient="records")
    ]
    df = pd.DataFrame(rows)

    wz = scoring_cfg.get("winsorize", {"lower_pct": 0.05, "upper_pct": 0.95})
    df["profit_density_score"] = _pct_rank_winsor(
        df["profit_per_liter"], wz["lower_pct"], wz["upper_pct"]
    )
    df["absolute_profit_score"] = _pct_rank_winsor(
        df["expected_net_profit_usd"], wz["lower_pct"], wz["upper_pct"]
    )
    df["demand_heat_score"] = _minmax(df["heat_raw"])
    df["sell_through_score"] = _minmax(df["sell_through_raw"])

    weights = scoring_cfg["weights"]
    pen = scoring_cfg.get("penalties", {})
    hard = scoring_cfg.get("hard_filters", {})
    tiers = scoring_cfg.get("tiers", {"A": 70, "B": 55, "C": 40})
    comp_by_pid = (
        {r["product_id"]: r for r in compliance.to_dict(orient="records")}
        if not compliance.empty
        else {}
    )
    prod_by_pid = {p["product_id"]: p for p in products.to_dict(orient="records")}

    scores: list[Score] = []
    for r in df.to_dict(orient="records"):
        pid = r["product_id"]
        product = prod_by_pid.get(pid, {})
        comp = comp_by_pid.get(pid, {})
        reasons: list[str] = []

        base = 100.0 * (
            weights["profit_density"] * r["profit_density_score"]
            + weights["absolute_profit"] * r["absolute_profit_score"]
            + weights["demand_heat"] * r["demand_heat_score"]
            + weights["sell_through"] * r["sell_through_score"]
            + weights["shelf_life"] * r["shelf_life_score"]
            + weights["supply_reliability"] * r["supply_reliability_score"]
            + weights["operational_ease"] * r["ops_ease_score"]
            + weights["strategic_fit"] * r["strategic_fit_score"]
        )

        # --- penalties ---
        comp_status = comp.get("compliance_status", Compliance.GREEN.value)
        n_yellow = sum(
            1
            for k in ("category_risk", "food_safety_risk", "cosmetic_drug_risk")
            if comp.get(k) == Compliance.YELLOW.value
        )
        compliance_pen = _compliance_penalty(comp_status, n_yellow, pen)

        melt = str(product.get("melt_risk_level", "LOW")).upper()
        temp_pen = {"LOW": 0, "MEDIUM": pen.get("melt_medium", 8), "HIGH": pen.get("melt_high", 20)}.get(melt, 0)

        crush = str(product.get("crush_risk_level", "LOW")).upper()
        leak = str(product.get("leak_risk_level", "LOW")).upper()
        frag_pen = {"LOW": 0, "MEDIUM": pen.get("fragility_medium", 5), "HIGH": pen.get("fragility_high", 15)}.get(crush, 0)
        frag_pen += {"LOW": 0, "MEDIUM": pen.get("leak_medium", 4), "HIGH": pen.get("leak_high", 12)}.get(leak, 0)

        match_pen, match_block = _matching_penalty(r["match_confidence"], pen)

        data_pen = 0.0
        if r["volume_liter"] is None:
            data_pen += pen.get("missing_volume", 8)
            reasons.append("missing_volume")
        elif r["vol_estimated"]:
            reasons.append("volume_estimated_from_weight")
        if r["weight_missing"]:
            data_pen += pen.get("missing_weight", 5)
            reasons.append("missing_weight")
        if not r["has_us_sold_data"]:
            data_pen += pen.get("missing_us_sold_data", 8)
            reasons.append("missing_us_sold_data")
        if not r["has_jp_price"]:
            data_pen += pen.get("missing_jp_real_price", 8)
            reasons.append("missing_jp_real_price")

        # low absolute profit soft penalty
        low_thr = scoring_cfg.get("low_profit_usd_threshold", 3.0)
        if r["expected_net_profit_usd"] is not None and r["expected_net_profit_usd"] < low_thr:
            base -= scoring_cfg.get("low_profit_penalty", 6)
            reasons.append("low_absolute_profit")

        final = base - compliance_pen - temp_pen - frag_pen - match_pen - data_pen
        final = max(0.0, min(100.0, final))

        # --- hard filters -> tier ---
        blocked = False
        watchlist = False
        if comp_status == Compliance.RED.value:
            blocked = True
            reasons.append("compliance_red_block")
        if match_block:
            blocked = True
            reasons.append("match_confidence_below_threshold_block")
        if r["shelf_life_hardfail"]:
            if product.get("is_food"):
                watchlist = True
                reasons.append("food_shelf_life_unknown_or_short_watchlist")
        net = r["expected_net_profit_usd"]
        if net is None or net <= hard.get("min_expected_net_profit_usd", 0.01):
            watchlist = True
            reasons.append("non_positive_or_missing_profit_watchlist")

        if blocked:
            tier = PriorityTier.BLOCKED.value
        elif watchlist:
            tier = PriorityTier.WATCHLIST.value
        elif final >= tiers.get("A", 70):
            tier = PriorityTier.A.value
        elif final >= tiers.get("B", 55):
            tier = PriorityTier.B.value
        elif final >= tiers.get("C", 40):
            tier = PriorityTier.C.value
        else:
            tier = PriorityTier.WATCHLIST.value

        # recommended channel hint
        channel = "eBay + local pickup"
        if comp.get("shipping_risk") == Compliance.RED.value:
            channel = "Local pickup only (hazmat shipping risk)"
        elif comp_status == Compliance.YELLOW.value:
            channel = "Local pickup / small eBay test (needs review)"

        price_gap = None
        if r["us_expected_sold_price_usd"] and r["jp_cost_usd"]:
            price_gap = r["us_expected_sold_price_usd"] - r["jp_cost_usd"]

        scores.append(
            Score(
                run_id=run_id,
                product_id=pid,
                jp_cost_usd=r["jp_cost_usd"],
                us_expected_sold_price_usd=r["us_expected_sold_price_usd"],
                us_expected_net_price_usd=r["us_expected_net_price_usd"],
                expected_net_profit_usd=net,
                profit_margin_pct=r["profit_margin_pct"],
                profit_per_liter=r["profit_per_liter"],
                profit_per_lb=r["profit_per_lb"],
                price_gap_score=round(price_gap, 4) if price_gap is not None else 0.0,
                profit_density_score=round(r["profit_density_score"], 4),
                absolute_profit_score=round(r["absolute_profit_score"], 4),
                demand_heat_score=round(r["demand_heat_score"], 4),
                sell_through_score=round(r["sell_through_score"], 4),
                shelf_life_score=round(r["shelf_life_score"], 4),
                shelf_life_days_remaining=r["shelf_life_days_remaining"],
                supply_reliability_score=round(r["supply_reliability_score"], 4),
                ops_ease_score=round(r["ops_ease_score"], 4),
                strategic_fit_score=round(r["strategic_fit_score"], 4),
                base_score=round(base, 3),
                compliance_penalty=round(compliance_pen, 3),
                temperature_damage_penalty=float(temp_pen),
                fragility_penalty=float(frag_pen),
                matching_confidence_penalty=float(match_pen),
                data_missing_penalty=float(data_pen),
                final_score=round(final, 3),
                recommended_channel=channel,
                priority_tier=tier,
                reason_codes=sorted(set(reasons)),
                data_confidence=round(r["data_confidence"], 3),
                volume_used_liter=r["volume_liter"] or 0.0,
                weight_used_lb=r["weight_lb"] or 0.0,
            )
        )
    return scores
