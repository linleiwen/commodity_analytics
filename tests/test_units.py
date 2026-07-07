"""Unit tests for unit/price/shelf-life/fee normalizers."""

from __future__ import annotations

from datetime import date

from app import settings
from app.normalizers import platform_fees, price, shelf_life, units


def test_parse_pack_count_english_and_japanese():
    assert units.parse_pack_count("18 pieces 300g") == 18
    assert units.parse_pack_count("24個入") == 24
    assert units.parse_pack_count("x12") == 12
    assert units.parse_pack_count("no number here") is None


def test_parse_weight_grams():
    assert units.parse_weight_grams("300g") == 300.0
    assert units.parse_weight_grams("1.5kg") == 1500.0
    assert units.parse_weight_grams("1,200 g") == 1200.0


def test_volume_and_weight_conversions():
    assert units.volume_liters(20, 10, 5) == 1.0  # 1000 cm3
    assert round(units.grams_to_lb(453.59237), 4) == 1.0
    assert units.volume_liters(0, 10, 5) is None


def test_resolve_volume_prefers_dimensions_then_estimates():
    vol, wt, estimated, wt_missing = units.resolve_volume_weight(
        volume_liter=None, length_cm=20, width_cm=10, height_cm=5,
        weight_g=300, unit_size_text=None,
    )
    assert vol == 1.0 and wt == 300 and estimated is False and wt_missing is False

    vol2, _, estimated2, _ = units.resolve_volume_weight(
        volume_liter=None, length_cm=None, width_cm=None, height_cm=None,
        weight_g=350, unit_size_text=None,
    )
    assert estimated2 is True and vol2 is not None


def test_currency_conversion_jpy_and_usd():
    assert price.to_usd(1000, "JPY", jpy_rate=0.0067) == 6.7
    assert price.to_usd(10, "USD") == 10.0


def test_landed_jp_cost_prefers_tax_free():
    cost = price.landed_jp_cost_usd(
        1200, "JPY", tax_free_price=1091, tax_free_eligible=True, jpy_rate=0.0067
    )
    assert cost == round(1091 * 0.0067, 4)


def test_parse_expiration_formats():
    assert shelf_life.parse_expiration_date("2027.02.28") == date(2027, 2, 28)
    assert shelf_life.parse_expiration_date("2027年1月31日") == date(2027, 1, 31)
    assert shelf_life.parse_expiration_date("31.12.2026") == date(2026, 12, 31)
    # year-month only -> last day of month
    assert shelf_life.parse_expiration_date("2026.12") == date(2026, 12, 31)
    assert shelf_life.parse_expiration_date("garbage") is None


def test_shelf_life_score_bands_and_hardfail():
    cfg = settings.load_config("scoring")
    # non-food non-cosmetic -> flat non-perishable score
    score, fail = shelf_life.shelf_life_score(None, is_food=False, is_cosmetic=False, config=cfg)
    assert score == 1.0 and fail is False
    # food below minimum -> hard fail
    score, fail = shelf_life.shelf_life_score(30, is_food=True, is_cosmetic=False, config=cfg)
    assert fail is True
    # food with a year -> top band
    score, fail = shelf_life.shelf_life_score(400, is_food=True, is_cosmetic=False, config=cfg)
    assert score == 1.0 and fail is False


def test_net_profit_breakdown_and_density():
    econ = platform_fees.compute_net_profit(
        us_sold_price_usd=32.0, jp_cost_usd=7.3, volume_liter=2.16
    )
    assert econ["expected_net_profit_usd"] is not None
    assert econ["expected_net_profit_usd"] < 32.0 - 7.3  # fees reduce it
    density = platform_fees.profit_density(econ["expected_net_profit_usd"], 2.16)
    assert density is not None


def test_net_profit_missing_inputs_returns_none():
    econ = platform_fees.compute_net_profit(us_sold_price_usd=None, jp_cost_usd=5.0, volume_liter=1.0)
    assert econ["expected_net_profit_usd"] is None
