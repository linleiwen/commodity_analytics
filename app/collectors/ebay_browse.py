"""eBay Browse API collector (active US listings) -- spec 4.2.

Uses the OAuth2 client-credentials grant, then ``item_summary/search``. Responses are
cached under ``data/raw`` so re-runs within the cache TTL make no network calls.
Docs: https://developer.ebay.com/api-docs/buy/static/api-browse.html
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.observation import PriceObservation


class EbayBrowseCollector(BaseCollector):
    key = "ebay_browse"

    def _token(self, client: httpx.Client) -> str | None:
        cached = self.cached_json("oauth_token", ttl_hours=1.5)
        if cached and cached.get("access_token"):
            return cached["access_token"]
        creds = self.creds()
        resp = client.post(
            self.config["oauth_endpoint"],
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            auth=(creds["EBAY_CLIENT_ID"], creds["EBAY_CLIENT_SECRET"]),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        self.save_json("oauth_token", data)
        return data.get("access_token")

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)

        result = CollectResult()
        marketplace = os.environ.get(self.config.get("marketplace_env", "EBAY_MARKETPLACE_ID"), "EBAY_US")
        timeout = self.defaults.get("timeout_seconds", 30)
        try:
            with httpx.Client(timeout=timeout) as client:
                token = self._token(client)
                if not token:
                    return self.skip_result("ebay_browse: could not obtain OAuth token")
                headers = {
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": marketplace,
                }
                for product in products:
                    pid = product["product_id"]
                    query = product.get("ebay_query") or product.get("canonical_name_en")
                    if not query:
                        continue
                    self._throttle()
                    cache_key = f"search::{query}::{marketplace}"
                    payload = self.cached_json(cache_key)
                    url = self.config["endpoint"]
                    if payload is None:
                        resp = client.get(url, headers=headers,
                                          params={"q": query, "limit": 25, "filter": "buyingOptions:{FIXED_PRICE}"})
                        if resp.status_code != 200:
                            result.logs.append(self.log("failure", message=resp.text[:200],
                                                        query=query, url=url, http_status=resp.status_code))
                            continue
                        payload = resp.json()
                        self.save_json(cache_key, payload)
                    items = payload.get("itemSummaries", []) or []
                    for it in items:
                        result.observations.append(self._to_obs(pid, query, it))
                    result.logs.append(self.log("success", query=query, url=url, records=len(items)))
        except httpx.HTTPError as exc:
            result.logs.append(self.log("failure", message=f"http error: {exc}"))
        return result

    def _to_obs(self, pid: str, query: str, it: dict[str, Any]) -> PriceObservation:
        price = (it.get("price") or {})
        ship = 0.0
        shipping_opts = it.get("shippingOptions") or []
        if shipping_opts:
            ship = util.as_float((shipping_opts[0].get("shippingCost") or {}).get("value"), 0.0)
        title = it.get("title", "")
        return PriceObservation(
            run_id=self.run_id,
            product_id=pid,
            source_name="eBay",
            source_type="api",
            source_url=it.get("itemWebUrl", ""),
            observed_at="",
            country="US",
            platform="eBay",
            listing_title=title,
            listing_id=str(it.get("itemId", "")),
            seller_name_hash=util.anonymize((it.get("seller") or {}).get("username")),
            condition=it.get("condition", ""),
            currency=price.get("currency", "USD"),
            price=util.as_float(price.get("value")),
            shipping_price=ship,
            availability_status="active",
            match_confidence=self.match_confidence(pid, title),
            confidence_level=ConfidenceLevel.API_VERIFIED.value,
        )
