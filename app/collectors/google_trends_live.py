"""Live Google Trends collector via ``pytrends`` (spec 4.3).

The official Trends API is alpha/allowlisted, so this uses the community ``pytrends``
client, which reads Google's public "interest over time" endpoint. It needs no API key
but is unofficial and easily rate-limited, so requests are throttled + cached and any
failure degrades to a logged skip (never raises).

For each product it queries relative search interest (0-100) over a recent window for the
configured geographies (national US plus optional DMV states DC / MD / VA), computes a
linear trend slope, and emits one ``trend`` demand signal per product.

Install with:  ``pip install ".[trends]"``

If you would rather export CSVs by hand, use ``manual-import --type google_trends``; this
collector and that importer both feed the same ``demand_signals`` table.
"""

from __future__ import annotations

import time
from typing import Any

from app.collectors.base import BaseCollector, CollectResult
from app.models import ConfidenceLevel
from app.models.social import DemandSignal

# Interest thresholds (mean 0-100 over the window) -> qualitative heat label.
_HEAT_BANDS = [(60.0, "viral"), (30.0, "high"), (10.0, "medium"), (0.0, "low")]


def _heat_label(mean_interest: float) -> str:
    for threshold, label in _HEAT_BANDS:
        if mean_interest >= threshold:
            return label
    return "low"


def _slope(values: list[float]) -> float:
    """Least-squares slope of interest vs. time index (per step). 0 if too few points."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    return round(num / denom, 4)


class GoogleTrendsLiveCollector(BaseCollector):
    key = "google_trends"

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:
        skip = self.preflight()
        if skip:
            return self.skip_result(skip)

        try:
            from pytrends.request import TrendReq
        except ImportError:
            return self.skip_result(
                "google_trends: pytrends not installed (pip install '.[trends]')"
            )

        result = CollectResult()
        geos: list[str] = self.config.get("geos", ["US"]) or ["US"]
        timeframe: str = self.config.get("timeframe", "today 3-m")
        hl: str = self.config.get("hl", "en-US")
        tz: int = int(self.config.get("tz", 360))
        geo_pause = float(self.config.get("geo_pause_seconds", 1.0))

        try:
            pytrends = TrendReq(hl=hl, tz=tz)
        except Exception as exc:  # noqa: BLE001 - unofficial client, be defensive
            return self.skip_result(f"google_trends: client init failed: {exc}")

        for product in products:
            pid = product["product_id"]
            query = product.get("canonical_name_en")
            if not query:
                continue

            national_mean = 0.0
            national_slope = 0.0
            geo_summ: list[str] = []
            any_success = False

            for geo in geos:
                self._throttle()
                cache_key = f"iot::{query}::{geo}::{timeframe}"
                series = self.cached_json(cache_key)
                if series is None:
                    try:
                        pytrends.build_payload([query], timeframe=timeframe, geo=geo)
                        df = pytrends.interest_over_time()
                    except Exception as exc:  # noqa: BLE001
                        result.logs.append(
                            self.log("failure", message=f"{geo}: {str(exc)[:150]}", query=f"{query}@{geo}")
                        )
                        time.sleep(geo_pause)
                        continue
                    if df is None or df.empty or query not in df.columns:
                        series = []
                    else:
                        series = [float(v) for v in df[query].tolist()]
                    self.save_json(cache_key, series)

                if not series:
                    geo_summ.append(f"{geo}=n/a")
                    continue

                any_success = True
                mean_interest = round(sum(series) / len(series), 2)
                latest = series[-1]
                slp = _slope(series)
                geo_summ.append(f"{geo}={latest:.0f}(avg{mean_interest:.0f},slope{slp:+.2f})")
                if geo.upper() == "US":
                    national_mean = mean_interest
                    national_slope = slp
                time.sleep(geo_pause)

            if not any_success:
                result.logs.append(self.log("failure", message="no interest data", query=query))
                continue

            # Fall back to the first successful geo if national US was not requested.
            if national_mean == 0.0 and geo_summ:
                for geo in geos:
                    s = self.cached_json(f"iot::{query}::{geo}::{timeframe}")
                    if s:
                        national_mean = round(sum(s) / len(s), 2)
                        national_slope = _slope(s)
                        break

            result.signals.append(
                DemandSignal(
                    run_id=self.run_id,
                    product_id=pid,
                    source_name="GoogleTrends",
                    query=query,
                    observed_at="",
                    window_days=self.config.get("window_days", 90),
                    signal_kind="trend",
                    mention_count=int(round(national_mean)),
                    trend_slope=national_slope,
                    manual_heat_label=_heat_label(national_mean),
                    notes="; ".join(geo_summ),
                    confidence_level=ConfidenceLevel.MANUAL_VERIFIED.value,
                )
            )
            result.logs.append(self.log("success", query=query, records=1))

        return result
