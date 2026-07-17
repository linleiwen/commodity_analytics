"""YouTube Data API v3 collector (English-audience demand signal) -- spec 4.3.

Searches haul/souvenir videos per product, then fetches real engagement statistics
(views / likes / comments) for the matched videos via ``videos.list``. Video count alone
is a weak proxy; actual view + engagement volume is a much better demand signal.

Quota note: ``search.list`` costs 100 units, ``videos.list`` costs 1 unit, so the extra
stats call is essentially free against the default 10k/day quota.

Docs: https://developers.google.com/youtube/v3
"""

from __future__ import annotations

from typing import Any

import httpx

from app import util
from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.social import DemandSignal

_QUERY_SUFFIX = "japan haul"
_VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"

# Total views over the matched sample -> qualitative heat label.
_HEAT_BANDS = [(1_000_000.0, "viral"), (200_000.0, "high"), (30_000.0, "medium"), (0.0, "low")]


def _heat_label(total_views: float) -> str:
    for threshold, label in _HEAT_BANDS:
        if total_views >= threshold:
            return label
    return "low"


class YouTubeCollector(BaseCollector):
    key = "youtube"

    def _fetch_stats(self, client: httpx.Client, video_ids: list[str], api_key: str) -> dict[str, int]:
        """Sum view/like/comment counts for up to 50 video ids (one videos.list call)."""
        totals = {"views": 0, "likes": 0, "comments": 0}
        if not video_ids:
            return totals
        cache_key = "stats::" + ",".join(sorted(video_ids))
        payload = self.cached_json(cache_key)
        if payload is None:
            self._throttle()
            resp = client.get(
                _VIDEOS_ENDPOINT,
                params={"part": "statistics", "id": ",".join(video_ids[:50]), "key": api_key},
            )
            if resp.status_code != 200:
                return totals
            payload = resp.json()
            self.save_json(cache_key, payload)
        for item in payload.get("items", []) or []:
            stats = item.get("statistics", {})
            totals["views"] += util.as_int(stats.get("viewCount"), 0)
            totals["likes"] += util.as_int(stats.get("likeCount"), 0)
            totals["comments"] += util.as_int(stats.get("commentCount"), 0)
        return totals

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
                    query = f"{base} {_QUERY_SUFFIX}"
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
                    video_ids = [
                        (it.get("id") or {}).get("videoId")
                        for it in items
                        if (it.get("id") or {}).get("videoId")
                    ]
                    stats = self._fetch_stats(client, video_ids, api_key)
                    engagement = float(stats["likes"] + stats["comments"])
                    result.signals.append(
                        DemandSignal(
                            run_id=self.run_id,
                            product_id=pid,
                            source_name="YouTube",
                            query=query,
                            signal_kind="social",
                            post_count=len(items),
                            mention_count=total,
                            view_count=stats["views"],
                            like_count=stats["likes"],
                            comment_count=stats["comments"],
                            engagement_score=engagement,
                            manual_heat_label=_heat_label(stats["views"]),
                            confidence_level=ConfidenceLevel.API_VERIFIED.value,
                        )
                    )
                    result.logs.append(
                        self.log("success", query=query, records=len(items),
                                 message=f"videos={len(items)} views={stats['views']}")
                    )
        except httpx.HTTPError as exc:
            result.logs.append(self.log("failure", message=f"http error: {exc}"))
        return result
