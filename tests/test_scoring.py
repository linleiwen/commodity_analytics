"""Compliance, scoring, and luggage-optimizer tests (spec sections 3, 9, 10)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.models import Compliance, PriorityTier
from app.models.score import Score
from app.scoring import compliance_rules, luggage_optimizer, score_engine


# --------------------------------------------------------------------------- compliance
def _product(**kw):
    base = {
        "product_id": "p", "canonical_name_en": "", "canonical_name_jp": "",
        "canonical_name_cn": "", "category": "", "brand": "", "notes": "", "risk_notes": "",
        "is_food": False, "is_cosmetic": False, "is_drug_or_otc_risk": False,
    }
    base.update(kw)
    return base


def test_sunscreen_is_red(risk_cfg):
    p = _product(canonical_name_en="Anessa Sunscreen SPF50", category="sunscreen",
                 is_cosmetic=True, is_drug_or_otc_risk=True)
    review = compliance_rules.evaluate(p, risk_cfg, "run")
    assert review.compliance_status == Compliance.RED.value


def test_eye_drops_is_red(risk_cfg):
    p = _product(canonical_name_en="Japanese Eye Drops", category="otc_drug",
                 is_drug_or_otc_risk=True)
    review = compliance_rules.evaluate(p, risk_cfg, "run")
    assert review.compliance_status == Compliance.RED.value


def test_refrigerated_food_is_red(risk_cfg):
    p = _product(canonical_name_en="Royce Nama Chocolate", category="food_souvenir_chocolate",
                 is_food=True, risk_notes="refrigerated nama chocolate")
    review = compliance_rules.evaluate(p, risk_cfg, "run")
    assert review.compliance_status == Compliance.RED.value
    assert review.food_safety_risk == Compliance.RED.value


def test_dairy_cookie_is_yellow(risk_cfg):
    p = _product(canonical_name_en="Tokyo Milk Cheese Cookie", category="food_souvenir_cookie",
                 is_food=True, risk_notes="dairy cheese")
    review = compliance_rules.evaluate(p, risk_cfg, "run")
    assert review.compliance_status == Compliance.YELLOW.value


def test_plush_is_green(risk_cfg):
    p = _product(canonical_name_en="Sanrio Plush Keychain", category="non_food_gift")
    review = compliance_rules.evaluate(p, risk_cfg, "run")
    assert review.compliance_status == Compliance.GREEN.value


def test_perfume_hazmat_shipping_risk(risk_cfg):
    p = _product(canonical_name_en="Fancy Perfume", category="cosmetics_makeup", is_cosmetic=True)
    review = compliance_rules.evaluate(p, risk_cfg, "run")
    assert review.shipping_risk == Compliance.RED.value


# --------------------------------------------------------------------------- scoring
def _score_frames():
    products = pd.DataFrame([
        {"product_id": "gift", "canonical_name_en": "Sanrio Goods", "category": "non_food_gift",
         "category_group": "non_food_gifts", "is_food": False, "is_cosmetic": False,
         "package_volume_liter": 0.5, "package_weight_g": 120, "limited_edition_flag": False,
         "melt_risk_level": "LOW", "crush_risk_level": "LOW", "leak_risk_level": "LOW",
         "default_shelf_life_days": None, "brand": "Sanrio"},
        {"product_id": "food_noexp", "canonical_name_en": "Mystery Snack", "category": "food_souvenir_snack",
         "category_group": "food", "is_food": True, "is_cosmetic": False,
         "package_volume_liter": 0.8, "package_weight_g": 180, "limited_edition_flag": False,
         "melt_risk_level": "LOW", "crush_risk_level": "HIGH", "leak_risk_level": "LOW",
         "default_shelf_life_days": None, "brand": ""},
    ])
    observations = pd.DataFrame([
        {"product_id": "gift", "country": "JP", "price_usd": 8.0, "source_type": "manual",
         "availability_status": "in_store", "expiration_date_parsed": "", "confidence_score": 0.85,
         "match_confidence": 0.95},
        {"product_id": "food_noexp", "country": "JP", "price_usd": 5.0, "source_type": "manual",
         "availability_status": "in_store", "expiration_date_parsed": "", "confidence_score": 0.85,
         "match_confidence": 0.95},
    ])
    signals = pd.DataFrame([
        {"product_id": "gift", "signal_kind": "sell_through", "median_sold_price": 22.0,
         "sold_count": 100, "sell_through_pct": 80, "competitor_count": 10, "days_to_sell": 6,
         "source_name": "eBayTerapeak", "confidence_score": 0.85, "mention_count": 0,
         "post_count": 0, "engagement_score": 0, "like_count": 0, "save_count": 0,
         "comment_count": 0, "share_count": 0, "buyer_intent_count": 0, "trend_slope": 0,
         "manual_heat_label": ""},
    ])
    return products, observations, signals


def test_compute_scores_blocks_and_watchlists(scoring_cfg, risk_cfg):
    products, observations, signals = _score_frames()
    compliance = pd.DataFrame([
        compliance_rules.evaluate(p, risk_cfg, "run").to_row()
        for p in products.to_dict(orient="records")
    ])
    scores = score_engine.compute_scores(
        products, observations, signals, compliance, scoring_cfg, date(2026, 8, 5), "run"
    )
    by_pid = {s.product_id: s for s in scores}
    # Food with unknown shelf life must not be a Buy tier.
    assert by_pid["food_noexp"].priority_tier == PriorityTier.WATCHLIST.value
    # The GREEN gift with real US sold data and profit should be scored positively.
    assert by_pid["gift"].final_score > 0
    assert by_pid["gift"].expected_net_profit_usd is not None


# --------------------------------------------------------------------------- luggage
def test_luggage_respects_volume_and_yellow_caps():
    scores = [
        Score(product_id="a", priority_tier="A", final_score=90,
              expected_net_profit_usd=5.0, volume_used_liter=0.5, weight_used_lb=0.3),
        Score(product_id="b", priority_tier="A", final_score=80,
              expected_net_profit_usd=4.0, volume_used_liter=0.5, weight_used_lb=0.3),
    ]
    products = {
        "a": {"category_group": "non_food_gifts", "melt_risk_level": "LOW",
              "crush_risk_level": "LOW", "leak_risk_level": "LOW"},
        "b": {"category_group": "cosmetic", "melt_risk_level": "LOW",
              "crush_risk_level": "LOW", "leak_risk_level": "LOW"},
    }
    compliance = {
        "a": {"compliance_status": "GREEN"},
        "b": {"compliance_status": "YELLOW"},
    }
    suitcase = {
        "suitcases": [{"usable_volume_liter": 3.0, "max_weight_lb": 10,
                       "reserved_volume_liter": 0, "reserved_weight_lb": 0}],
        "business_constraints": {"max_skus": 40, "max_units_per_sku_default": 6,
                                 "max_units_per_yellow_risk_sku": 2, "diversity_bonus": False},
    }
    updated, plan = luggage_optimizer.optimize(scores, products, compliance, suitcase)
    by_pid = {s.product_id: s for s in updated}
    # YELLOW item capped at 2 units.
    assert by_pid["b"].recommended_qty <= 2
    # Total packed volume must not exceed available volume.
    assert plan.volume_used_liter <= plan.available_volume_liter + 1e-6
    assert plan.total_estimated_profit > 0
