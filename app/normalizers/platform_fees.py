"""Platform fees and net-profit computation (spec 2.1).

All fee assumptions live in one dataclass so they can be surfaced verbatim in the Excel
``Assumptions`` tab and tuned without touching the scoring math.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FeeAssumptions:
    # eBay-style marketplace fees (managed payments bundle processing into the FVF).
    platform_fee_pct: float = 0.1325          # final value fee (blended category avg)
    platform_fixed_fee_usd: float = 0.30      # per-order fixed fee
    payment_fee_pct: float = 0.0              # extra processing allowance (0 if bundled)
    # Fulfillment / handling.
    expected_shipping_subsidy_usd: float = 3.00  # blended; 0 for pure local pickup
    packaging_cost_usd: float = 1.25
    # Import / tax allowances (small-batch personal import; verify per-item manually).
    customs_duty_pct: float = 0.0
    sales_tax_admin_pct: float = 0.0
    # Risk allowance for damage / returns as a fraction of sold price.
    damage_return_allowance_pct: float = 0.04
    # Opportunity cost of scarce luggage space.
    suitcase_space_cost_per_liter_usd: float = 1.20

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


DEFAULT_FEES = FeeAssumptions()


def compute_net_profit(
    *,
    us_sold_price_usd: float | None,
    jp_cost_usd: float | None,
    volume_liter: float | None,
    fees: FeeAssumptions = DEFAULT_FEES,
) -> dict[str, float | None]:
    """Return a full net-profit breakdown for one unit.

    Missing sold price or JP cost yields ``expected_net_profit_usd = None`` (excluded by
    the score engine's hard filter on positive profit).
    """
    if us_sold_price_usd is None or jp_cost_usd is None:
        return {
            "expected_net_profit_usd": None,
            "us_expected_net_price_usd": None,
            "profit_margin_pct": None,
            "platform_fee_usd": None,
            "suitcase_space_cost_usd": None,
        }

    sold = float(us_sold_price_usd)
    cost = float(jp_cost_usd)
    vol = float(volume_liter) if volume_liter and volume_liter > 0 else 0.0

    platform_fee = sold * fees.platform_fee_pct + fees.platform_fixed_fee_usd
    payment_fee = sold * fees.payment_fee_pct
    customs = cost * fees.customs_duty_pct
    tax_admin = sold * fees.sales_tax_admin_pct
    damage = sold * fees.damage_return_allowance_pct
    space_cost = vol * fees.suitcase_space_cost_per_liter_usd

    total_costs = (
        cost
        + platform_fee
        + payment_fee
        + fees.expected_shipping_subsidy_usd
        + fees.packaging_cost_usd
        + customs
        + tax_admin
        + damage
        + space_cost
    )
    net = sold - total_costs
    net_price = sold - platform_fee - payment_fee  # revenue net of platform take

    return {
        "expected_net_profit_usd": round(net, 4),
        "us_expected_net_price_usd": round(net_price, 4),
        "profit_margin_pct": round(net / sold, 4) if sold > 0 else None,
        "platform_fee_usd": round(platform_fee + payment_fee, 4),
        "suitcase_space_cost_usd": round(space_cost, 4),
    }


def profit_density(net_profit_usd: float | None, volume_liter: float | None) -> float | None:
    if net_profit_usd is None or not volume_liter or volume_liter <= 0:
        return None
    return round(net_profit_usd / volume_liter, 4)


def profit_per_lb(net_profit_usd: float | None, weight_lb: float | None) -> float | None:
    if net_profit_usd is None or not weight_lb or weight_lb <= 0:
        return None
    return round(net_profit_usd / weight_lb, 4)
