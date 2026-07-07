"""Yahoo! Shopping Japan API collector (JP online prices) -- spec 4.1.

Docs: https://developer.yahoo.co.jp/webapi/shopping/
"""

from __future__ import annotations

from typing import Any

import httpx

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.observation import PriceObservation


class YahooJpShoppingCollector(BaseCollector):
    key = "yahoo_jp_shopping"

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)

        result = CollectResult()
        app_id = self.creds().get("YAHOO_JP_APP_ID", "")
        endpoint = self.config["endpoint"]
        timeout = self.defaults.get("timeout_seconds", 30)
        try:
            with httpx.Client(timeout=timeout) as client:
                for product in products:
                    pid = product["product_id"]
                    query = product.get("canonical_name_jp") or product.get("canonical_name_en")
                    if not query:
                        continue
                    self._throttle()
                    cache_key = f"search::{query}"
                    payload = self.cached_json(cache_key)
                    if payload is None:
                        resp = client.get(
                            endpoint,
                            params={"appid": app_id, "query": query, "results": 20},
                        )
                        if resp.status_code != 200:
                            result.logs.append(self.log("failure", message=resp.text[:200],
                                                        query=query, url=endpoint,
                                                        http_status=resp.status_code))
                            continue
                        payload = resp.json()
                        self.save_json(cache_key, payload)
                    hits = payload.get("hits", []) or []
                    for it in hits:
                        result.observations.append(self._to_obs(pid, it))
                    result.logs.append(self.log("success", query=query, url=endpoint, records=len(hits)))
        except httpx.HTTPError as exc:
            result.logs.append(self.log("failure", message=f"http error: {exc}"))
        return result

    def _to_obs(self, pid: str, it: dict[str, Any]) -> PriceObservation:
        title = it.get("name", "")
        review = it.get("review") or {}
        seller = it.get("seller") or {}
        return PriceObservation(
            run_id=self.run_id,
            product_id=pid,
            source_name="YahooJP",
            source_type="api",
            source_url=it.get("url", ""),
            country="JP",
            platform="YahooJP",
            listing_title=title,
            listing_id=str(it.get("code", "")),
            seller_name_hash=util.anonymize(seller.get("name")),
            condition="new",
            currency="JPY",
            price=util.as_float(it.get("price")),
            shipping_price=0.0,
            availability_status="in_stock",
            rating=util.as_float(review.get("rate")),
            review_count=util.as_int(review.get("count")),
            match_confidence=self.match_confidence(pid, title),
            confidence_level=ConfidenceLevel.API_VERIFIED.value,
        )
