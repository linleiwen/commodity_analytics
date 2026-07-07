"""YouTube Data API v3 collector (English-audience demand signal) -- spec 4.3.

Counts matching haul/souvenir videos per product as a demand proxy.
Docs: https://developers.google.com/youtube/v3
"""

from __future__ import annotations

from typing import Any

import httpx

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.social import DemandSignal

_QUERY_SUFFIXES = ["japan haul", "review", "taste test", "souvenir"]


class YouTubeCollector(BaseCollector):
    key = "youtube"

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)

        result = CollectResult()
        api_key = self.creds().get("YOUTUBE_API_KEY", "")
        endpoint = self.config["endpoint"]
        timeout = self.defaults.get("timeout_seconds", 30)
        try:
            with httpx.Client(timeout=timeout) as client:
                for product in products:
                    pid = product["product_id"]
                    base = product.get("canonical_name_en")
                    if not base:
                        continue
                    query = f"{base} {_QUERY_SUFFIXES[0]}"
                    self._throttle()
                    cache_key = f"search::{query}"
                    payload = self.cached_json(cache_key)
                    if payload is None:
                        resp = client.get(
                            endpoint,
                            params={"part": "snippet", "q": query, "type": "video",
                                    "maxResults": 25, "key": api_key},
                        )
                        if resp.status_code != 200:
                            result.logs.append(self.log("failure", message=resp.text[:200],
                                                        query=query, url=endpoint,
                                                        http_status=resp.status_code))
                            continue
                        payload = resp.json()
                        self.save_json(cache_key, payload)
                    items = payload.get("items", []) or []
                    total = util.as_int((payload.get("pageInfo") or {}).get("totalResults"), len(items))
                    result.signals.append(
                        DemandSignal(
                            run_id=self.run_id,
                            product_id=pid,
                            source_name="YouTube",
                            query=query,
                            signal_kind="social",
                            post_count=len(items),
                            mention_count=total,
                            confidence_level=ConfidenceLevel.API_VERIFIED.value,
                        )
                    )
                    result.logs.append(self.log("success", query=query, records=len(items)))
        except httpx.HTTPError as exc:
            result.logs.append(self.log("failure", message=f"http error: {exc}"))
        return result
