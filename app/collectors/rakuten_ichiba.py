"""Rakuten Ichiba Item Search API collector (JP online prices) -- spec 4.1.

Docs: https://webservice.rakuten.co.jp/documentation/ichiba-item-search
"""

from __future__ import annotations

from typing import Any

import httpx

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.observation import PriceObservation


class RakutenIchibaCollector(BaseCollector):
    key = "rakuten_ichiba"

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)

        result = CollectResult()
        creds = self.creds()
        app_id = creds.get("RAKUTEN_APP_ID", "")
        access_key = creds.get("RAKUTEN_ACCESS_KEY", "")  # pk_...; required since Feb-2026 API
        endpoint = self.config["endpoint"]
        timeout = self.defaults.get("timeout_seconds", 30)
        try:
            with httpx.Client(timeout=timeout) as client:
                for product in products:
                    pid = product["product_id"]
                    keyword = product.get("canonical_name_jp") or product.get("canonical_name_en")
                    if not keyword:
                        continue
                    self._throttle()
                    cache_key = f"search::{keyword}"
                    payload = self.cached_json(cache_key)
                    if payload is None:
                        resp = client.get(
                            endpoint,
                            params={"applicationId": app_id, "accessKey": access_key,
                                    "keyword": keyword, "hits": 20, "format": "json"},
                        )
                        if resp.status_code != 200:
                            result.logs.append(self.log("failure", message=resp.text[:200],
                                                        query=keyword, url=endpoint,
                                                        http_status=resp.status_code))
                            continue
                        payload = resp.json()
                        self.save_json(cache_key, payload)
                    items = payload.get("Items", []) or []
                    for wrap in items:
                        it = wrap.get("Item", {})
                        result.observations.append(self._to_obs(pid, it))
                    result.logs.append(self.log("success", query=keyword, url=endpoint, records=len(items)))
        except httpx.HTTPError as exc:
            result.logs.append(self.log("failure", message=f"http error: {exc}"))
        return result

    def _to_obs(self, pid: str, it: dict[str, Any]) -> PriceObservation:
        title = it.get("itemName", "")
        return PriceObservation(
            run_id=self.run_id,
            product_id=pid,
            source_name="Rakuten",
            source_type="api",
            source_url=it.get("itemUrl", ""),
            country="JP",
            platform="Rakuten",
            listing_title=title,
            listing_id=str(it.get("itemCode", "")),
            seller_name_hash=util.anonymize(it.get("shopName")),
            condition="new",
            currency="JPY",
            price=util.as_float(it.get("itemPrice")),
            shipping_price=0.0,
            availability_status="in_stock" if it.get("availability") == 1 else "unknown",
            rating=util.as_float(it.get("reviewAverage")),
            review_count=util.as_int(it.get("reviewCount")),
            match_confidence=self.match_confidence(pid, title),
            confidence_level=ConfidenceLevel.API_VERIFIED.value,
        )
