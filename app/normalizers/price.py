"""Currency conversion and price normalization."""

from __future__ import annotations

from app import settings

JP_CONSUMPTION_TAX = 0.10  # 10% standard rate; food is often 8% (reduced) but we stay conservative


def to_usd(amount: float | None, currency: str | None, jpy_rate: float | None = None) -> float | None:
    """Convert an amount in a supported currency to USD.

    ``jpy_rate`` is USD per 1 JPY; defaults to the configured/env rate.
    """
    if amount is None:
        return None
    cur = (currency or "").strip().upper()
    if cur in {"USD", "US$", "$", ""}:
        # Empty currency defaults to USD for US-side observations; JP side always tags JPY.
        return round(float(amount), 4)
    if cur in {"JPY", "YEN", "¥", "JP"}:
        rate = jpy_rate if jpy_rate is not None else settings.jpy_to_usd_rate()
        return round(float(amount) * rate, 4)
    # Unknown currency: return as-is but caller should treat with low confidence.
    return round(float(amount), 4)


def effective_jp_cost_jpy(
    price_jpy: float | None,
    tax_included: bool | None,
    tax_free_price_jpy: float | None,
    tax_free_eligible: bool | None,
) -> float | None:
    """Pick the most realistic JP acquisition cost in JPY.

    Preference: an explicit tax-free price (if eligible) → the observed price
    (tax-inclusive prices are kept as-is since that is what you actually pay at register).
    """
    if tax_free_eligible and tax_free_price_jpy and tax_free_price_jpy > 0:
        return float(tax_free_price_jpy)
    if price_jpy is None:
        return None
    return float(price_jpy)


def landed_jp_cost_usd(
    price: float | None,
    currency: str | None,
    *,
    tax_included: bool | None = None,
    tax_free_price: float | None = None,
    tax_free_eligible: bool | None = None,
    jpy_rate: float | None = None,
) -> float | None:
    """Compute the JP purchase cost in USD, honoring tax-free eligibility for JPY prices."""
    cur = (currency or "").strip().upper()
    if cur in {"JPY", "YEN", "¥", "JP"}:
        jpy = effective_jp_cost_jpy(price, tax_included, tax_free_price, tax_free_eligible)
        return to_usd(jpy, "JPY", jpy_rate)
    return to_usd(price, currency, jpy_rate)
