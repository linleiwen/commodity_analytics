"""Keepa collector (Amazon price history / stability) -- spec 4.2.

Uses the optional ``keepa`` package when installed and ``KEEPA_API_KEY`` is set. Queries
by US ASIN (skips products without one). Emits a US price observation plus a lightweight
price-stability note. Disabled by default in ``sources.yaml`` (paid API).
Docs: https://keepaapi.readthedocs.io/
"""

from __future__ import annotations

from typing import Any

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.observation import PriceObservation


class KeepaCollector(BaseCollector):
    key = "keepa"

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)
        try:
            import keepa  # type: ignore
        except Exception:
            return self.skip_result("keepa: install optional dep `pip install keepa` to enable")

        import os

        result = CollectResult()
        asins = [(p["product_id"], p.get("asin_us")) for p in products if p.get("asin_us")]
        if not asins:
            return self.skip_result("keepa: no products have asin_us; nothing to query")
        try:
            api = keepa.Keepa(os.environ["KEEPA_API_KEY"])
        except Exception as exc:  # noqa: BLE001
            return self.skip_result(f"keepa: client init failed: {exc}")

        for pid, asin in asins:
            self._throttle()
            try:
                products_data = api.query(asin, domain="US")
            except Exception as exc:  # noqa: BLE001
                result.logs.append(self.log("failure", message=str(exc)[:200], query=str(asin)))
                continue
            for data in products_data:
                stats = data.get("stats", {}) or {}
                current = stats.get("current", []) or []
                amazon_cents = current[0] if current else None
                price = (amazon_cents / 100.0) if isinstance(amazon_cents, (int, float)) and amazon_cents > 0 else None
                result.observations.append(
                    PriceObservation(
                        run_id=self.run_id, product_id=pid, source_name="Keepa",
                        source_type="api", country="US", platform="Keepa",
                        listing_title=data.get("title", ""), listing_id=str(asin),
                        currency="USD", price=price, availability_status="history",
                        match_confidence=0.90, confidence_level=ConfidenceLevel.API_VERIFIED.value,
                    )
                )
            result.logs.append(self.log("success", query=str(asin), records=len(products_data)))
        return result
