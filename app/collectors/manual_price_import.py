"""Manual CSV importers (spec section 12).

Supported ``--type`` values:

* ``field_prices``   -> JP field-survey purchase records (price + package + shelf-life).
* ``terapeak``       -> eBay Terapeak/Product-Research sell-through export.
* ``social_notes``   -> hand-sampled social heat (Xiaohongshu / TikTok / etc.).
* ``google_trends``  -> Google Trends export (relative interest + slope).

Rows are matched to Product Master by ``product_id`` (if given) or ``product_name``.
Unmatched rows are skipped and logged so the QA report can surface them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.observation import PriceObservation
from app.models.social import DemandSignal
from app.normalizers import shelf_life, units
from app.normalizers.product_match import ProductMatcher
from app.storage import db

MANUAL_TYPES = {"field_prices", "terapeak", "social_notes", "google_trends"}


def _norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _get(row: dict[str, Any], *names: str):
    for n in names:
        if n in row and pd.notna(row[n]) and str(row[n]).strip() != "":
            return row[n]
    return None


class ManualImporter(BaseCollector):
    key = "manual_field_prices"  # base key; actual source label derived from manual_type

    def __init__(self, run_id: str, manual_type: str, matcher: ProductMatcher):
        super().__init__(run_id)
        if manual_type not in MANUAL_TYPES:
            raise ValueError(f"Unknown manual type '{manual_type}'. Known: {sorted(MANUAL_TYPES)}")
        self.manual_type = manual_type
        self.matcher = matcher

    def import_file(self, file_path: str | Path) -> CollectResult:
        path = Path(file_path)
        result = CollectResult()
        if not path.exists():
            result.logs.append(self.log("failure", message=f"file not found: {path}", url=str(path)))
            return result
        df = _norm_cols(pd.read_csv(path))
        handler: Callable[[dict[str, Any], CollectResult, str], None] = {
            "field_prices": self._field_price_row,
            "terapeak": self._terapeak_row,
            "social_notes": self._social_row,
            "google_trends": self._trends_row,
        }[self.manual_type]

        matched = 0
        for row in df.to_dict(orient="records"):
            pid, conf = self._resolve_product(row)
            if not pid:
                name = _get(row, "product_name", "product", "name") or "(blank)"
                result.logs.append(self.log("failure", message=f"unmatched product '{name}'", query=str(name)))
                continue
            handler(row, result, pid)
            matched += 1

        result.logs.append(
            self.log("success", message=f"{self.manual_type}: matched {matched}/{len(df)} rows",
                     url=str(path), records=matched)
        )
        return result

    def _resolve_product(self, row: dict[str, Any]) -> tuple[str | None, float]:
        pid = _get(row, "product_id")
        name = _get(row, "product_name", "product", "name")
        jan = _get(row, "jan", "jan_gtin", "gtin", "upc")
        m = self.matcher.match(title=str(name) if name else None,
                               jan=str(jan) if jan else None,
                               product_id=str(pid) if pid else None)
        if m.product_id and m.confidence >= 0.70:
            return m.product_id, m.confidence
        return None, m.confidence

    # ---- per-type row handlers -----------------------------------------
    def _field_price_row(self, row: dict[str, Any], result: CollectResult, pid: str) -> None:
        price_jpy = util.as_float(_get(row, "price_jpy", "price"))
        tax_free = util.as_float(_get(row, "tax_free_price_jpy", "tax_free_price"))
        # Bake the realistic acquisition cost into `price` (tax-free wins when cheaper),
        # so downstream normalization only needs a straight JPY -> USD conversion.
        effective_jpy = price_jpy
        if tax_free is not None and (price_jpy is None or tax_free < price_jpy):
            effective_jpy = tax_free
        expiry_text = _get(row, "expiry_text", "expiration", "expiry", "expiration_date")
        exp_date = shelf_life.parse_expiration_date(str(expiry_text) if expiry_text else None)

        length = util.as_float(_get(row, "length_cm"))
        width = util.as_float(_get(row, "width_cm"))
        height = util.as_float(_get(row, "height_cm"))
        weight_g = util.as_float(_get(row, "package_weight_g", "weight_g"))
        size_text = _get(row, "weight_or_size_text", "unit_size_text", "size_text")
        pack_count = util.as_int(_get(row, "package_count", "pack_count"))
        if pack_count is None and size_text:
            pack_count = units.parse_pack_count(str(size_text))
        if weight_g is None and size_text:
            weight_g = units.parse_weight_grams(str(size_text))
        vol = units.volume_liters(length, width, height)

        obs = PriceObservation(
            run_id=self.run_id,
            product_id=pid,
            source_name="FieldSurvey",
            source_type="manual",
            source_url=str(_get(row, "photo_price_tag", "photo_front") or ""),
            observed_at=str(_get(row, "purchase_date") or db.utcnow()),
            country="JP",
            platform="FieldSurvey",
            listing_title=str(_get(row, "product_name", "product") or ""),
            condition="new",
            currency="JPY",
            price=effective_jpy,
            sales_tax_included_flag=(tax_free is None) and util.as_bool(_get(row, "tax_included_flag"), True),
            tax_free_eligible_flag=tax_free is not None,
            availability_status="in_store",
            expiration_date_text=str(expiry_text or ""),
            expiration_date_parsed=exp_date.isoformat() if exp_date else "",
            match_confidence=0.95,
            confidence_level=ConfidenceLevel.MANUAL_VERIFIED.value,
        )
        result.observations.append(obs)
        # Product Master enrichment (only non-null fields overwrite existing values).
        result.product_updates.append(
            {
                "product_id": pid,
                "package_count": pack_count,
                "unit_size_text": str(size_text) if size_text else None,
                "package_weight_g": weight_g,
                "package_length_cm": length,
                "package_width_cm": width,
                "package_height_cm": height,
                "package_volume_liter": vol,
                "storage_condition": _get(row, "storage_condition"),
            }
        )

    def _terapeak_row(self, row: dict[str, Any], result: CollectResult, pid: str) -> None:
        sig = DemandSignal(
            run_id=self.run_id,
            product_id=pid,
            source_name="eBayTerapeak",
            query=str(_get(row, "search_term", "query", "product_name") or ""),
            observed_at=str(_get(row, "export_date", "observed_at") or db.utcnow()),
            window_days=util.as_int(_get(row, "period_days", "window_days"), 90),
            signal_kind="sell_through",
            sold_count=util.as_int(_get(row, "sold_count", "sold_quantity")),
            sell_through_pct=util.as_float(_get(row, "sell_through_pct", "sell_through")),
            median_sold_price=util.as_float(_get(row, "median_sold_price", "avg_sold_price", "median_price")),
            avg_shipping=util.as_float(_get(row, "avg_shipping", "average_shipping")),
            competitor_count=util.as_int(_get(row, "competitor_count", "seller_count")),
            days_to_sell=util.as_float(_get(row, "days_to_sell", "median_days_to_sell")),
            notes=str(_get(row, "notes", "same_pack_flag") or ""),
            confidence_level=ConfidenceLevel.MANUAL_VERIFIED.value,
        )
        result.signals.append(sig)

    def _social_row(self, row: dict[str, Any], result: CollectResult, pid: str) -> None:
        sig = DemandSignal(
            run_id=self.run_id,
            product_id=pid,
            source_name=str(_get(row, "platform", "source") or "SocialManual"),
            query=str(_get(row, "query", "post_title") or ""),
            source_url=str(_get(row, "post_url", "url") or ""),
            observed_at=str(_get(row, "post_date", "observed_at") or db.utcnow()),
            window_days=util.as_int(_get(row, "window_days"), 30),
            signal_kind="social",
            mention_count=util.as_int(_get(row, "mention_count")),
            post_count=util.as_int(_get(row, "post_count"), 1),
            view_count=util.as_int(_get(row, "view_count")),
            like_count=util.as_int(_get(row, "like_count")),
            save_count=util.as_int(_get(row, "save_count")),
            comment_count=util.as_int(_get(row, "comment_count")),
            share_count=util.as_int(_get(row, "share_count")),
            buyer_intent_count=util.as_int(_get(row, "buyer_intent_comment_count", "buyer_intent_count")),
            manual_heat_label=str(_get(row, "manual_heat_label", "heat_label") or "").lower(),
            notes=str(_get(row, "notes") or ""),
            confidence_level=ConfidenceLevel.SCRAPED_LOW.value,
        )
        result.signals.append(sig)

    def _trends_row(self, row: dict[str, Any], result: CollectResult, pid: str) -> None:
        sig = DemandSignal(
            run_id=self.run_id,
            product_id=pid,
            source_name="GoogleTrends",
            query=str(_get(row, "query", "keyword") or ""),
            observed_at=str(_get(row, "observed_at", "export_date") or db.utcnow()),
            window_days=util.as_int(_get(row, "window_days"), 90),
            signal_kind="trend",
            mention_count=util.as_int(_get(row, "trend_value", "interest")),
            trend_slope=util.as_float(_get(row, "trend_slope", "slope")),
            manual_heat_label=str(_get(row, "manual_heat_label") or "").lower(),
            notes=f"region={_get(row, 'region') or 'US'}; {_get(row, 'notes') or ''}".strip(),
            confidence_level=ConfidenceLevel.MANUAL_VERIFIED.value,
        )
        result.signals.append(sig)
