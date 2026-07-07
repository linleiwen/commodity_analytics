"""eBay Terapeak / Product Research import (spec 4.2, 12.2).

Terapeak sell-through data is not available via a public automated API on the buy side,
so it is exported by hand from Seller Hub and imported as a CSV. This module is a thin,
explicit entry point that delegates to :class:`ManualImporter` with ``type=terapeak``.

Expected columns (case-insensitive, extra columns ignored):
    product_name | product_id, search_term, median_sold_price, sold_count,
    sell_through_pct, avg_shipping, competitor_count, days_to_sell, period_days,
    same_pack_flag, notes
"""

from __future__ import annotations

from pathlib import Path

from app.collectors.base import CollectResult
from app.collectors.manual_price_import import ManualImporter
from app.normalizers.product_match import ProductMatcher


def import_csv(run_id: str, file_path: str | Path, matcher: ProductMatcher) -> CollectResult:
    return ManualImporter(run_id, "terapeak", matcher).import_file(file_path)
