"""Reddit Data API collector (English-audience demand signal) -- spec 4.3.

OAuth2 client-credentials (script app), then keyword search across configured subreddits.
Aggregates post count, upvotes, comments, and buyer-intent phrases into one social signal
per product. Docs: https://support.reddithelp.com/hc/en-us/articles/14945211791892
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.social import DemandSignal

_BUYER_INTENT_TERMS = ["where to buy", "can't find", "cant find", "how to get", "shipping",
                       "ship to", "dmv", "for sale", "looking for", "restock"]


class RedditCollector(BaseCollector):
    key = "reddit"

    def _token(self, client: httpx.Client) -> str | None:
        cached = self.cached_json("oauth_token", ttl_hours=0.9)
        if cached and cached.get("access_token"):
            return cached["access_token"]
        creds = self.creds()
        ua = os.environ.get("REDDIT_USER_AGENT", "japan-dmv-arbitrage/1.0")
        resp = client.post(
            self.config["oauth_endpoint"],
            data={"grant_type": "client_credentials"},
            auth=(creds["REDDIT_CLIENT_ID"], creds["REDDIT_CLIENT_SECRET"]),
            headers={"User-Agent": ua},
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
        ua = os.environ.get("REDDIT_USER_AGENT", "japan-dmv-arbitrage/1.0")
        subreddits = self.config.get("subreddits", [])
        timeout = self.defaults.get("timeout_seconds", 30)
        try:
            with httpx.Client(timeout=timeout) as client:
                token = self._token(client)
                if not token:
                    return self.skip_result("reddit: could not obtain OAuth token")
                headers = {"Authorization": f"Bearer {token}", "User-Agent": ua}
                for product in products:
                    pid = product["product_id"]
                    query = product.get("canonical_name_en")
                    if not query:
                        continue
                    posts, ups, comments, intent = 0, 0, 0, 0
                    for sub in subreddits:
                        self._throttle()
                        cache_key = f"search::{sub}::{query}"
                        payload = self.cached_json(cache_key)
                        url = f"https://oauth.reddit.com/r/{sub}/search"
                        if payload is None:
                            resp = client.get(url, headers=headers,
                                              params={"q": query, "restrict_sr": 1, "limit": 25, "sort": "relevance"})
                            if resp.status_code != 200:
                                result.logs.append(self.log("failure", message=resp.text[:150],
                                                            query=f"{sub}:{query}", url=url,
                                                            http_status=resp.status_code))
                                continue
                            payload = resp.json()
                            self.save_json(cache_key, payload)
                        children = (payload.get("data") or {}).get("children", [])
                        for ch in children:
                            d = ch.get("data", {})
                            posts += 1
                            ups += util.as_int(d.get("ups"), 0)
                            comments += util.as_int(d.get("num_comments"), 0)
                            text = f"{d.get('title', '')} {d.get('selftext', '')}".lower()
                            if any(term in text for term in _BUYER_INTENT_TERMS):
                                intent += 1
                    result.signals.append(
                        DemandSignal(
                            run_id=self.run_id,
                            product_id=pid,
                            source_name="Reddit",
                            query=query,
                            signal_kind="social",
                            post_count=posts,
                            mention_count=posts,
                            like_count=ups,
                            comment_count=comments,
                            buyer_intent_count=intent,
                            confidence_level=ConfidenceLevel.API_VERIFIED.value,
                        )
                    )
                    result.logs.append(self.log("success", query=query, records=posts))
        except httpx.HTTPError as exc:
            result.logs.append(self.log("failure", message=f"http error: {exc}"))
        return result
