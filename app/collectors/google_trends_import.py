"""Google Trends import (spec 4.3, 15.1).

The official Trends API is alpha/allowlisted, so relative-interest data is exported by
hand (or via a third-party helper) and imported as a CSV. Thin delegate to
:class:`ManualImporter` with ``type=google_trends``.

Expected columns (case-insensitive):
    product_name | product_id, query, region, trend_value, trend_slope,
    window_days, manual_heat_label, notes
"""

from __future__ import annotations

from pathlib import Path

from app.collectors.base import CollectResult
from app.collectors.manual_price_import import ManualImporter
from app.normalizers.product_match import ProductMatcher


def import_csv(run_id: str, file_path: str | Path, matcher: ProductMatcher) -> CollectResult:
    return ManualImporter(run_id, "google_trends", matcher).import_file(file_path)
