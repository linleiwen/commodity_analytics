"""Base collector: config access, credential checks, polite rate-limiting, caching, logging.

Subclasses implement :meth:`collect` and return a :class:`CollectResult`. The pipeline
persists the returned observations/signals and writes the log rows for auditability.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app import settings, util
from app.models.observation import PriceObservation
from app.models.social import DemandSignal
from app.storage import db


@dataclass
class CollectResult:
    observations: list[PriceObservation] = field(default_factory=list)
    signals: list[DemandSignal] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)
    # Field-survey imports enrich Product Master (weight/dims/pack/shelf-life).
    product_updates: list[dict[str, Any]] = field(default_factory=list)


class BaseCollector:
    """Common behaviour for all collectors. ``key`` maps to a ``config/sources.yaml`` entry."""

    key: str = ""

    def __init__(self, run_id: str, matcher=None):
        self.run_id = run_id
        self.matcher = matcher
        sources = settings.load_config("sources")
        self.defaults = sources.get("defaults", {})
        self.config = sources.get("sources", {}).get(self.key, {})
        self._last_call = 0.0

    def match_confidence(self, product_id: str, title: str | None) -> float:
        """Confidence that a listing title belongs to the product we queried for."""
        if not self.matcher or not title:
            return 0.72  # queried-by-term default (fuzzy band); not JAN-verified
        m = self.matcher.match(title=title, product_id=None)
        return m.confidence if m.product_id == product_id else min(m.confidence, 0.72)

    # --- config / gating -------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.config.get("enabled", False))

    @property
    def min_interval(self) -> float:
        env = os.environ.get("COLLECTOR_MIN_INTERVAL_SECONDS")
        if env:
            try:
                return float(env)
            except ValueError:
                pass
        return float(self.config.get("min_interval_seconds", self.defaults.get("min_interval_seconds", 2)))

    def missing_credentials(self) -> list[str]:
        return [name for name in self.config.get("credential_env", []) if not os.environ.get(name)]

    def creds(self) -> dict[str, str]:
        return {name: os.environ.get(name, "") for name in self.config.get("credential_env", [])}

    # --- rate limiting / caching ----------------------------------------
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _cache_path(self, *parts: str) -> Path:
        settings.ensure_dirs()
        digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
        return settings.RAW_DIR / f"{self.key}__{digest}.json"

    def cached_json(self, cache_key: str, ttl_hours: float | None = None):
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        ttl = ttl_hours if ttl_hours is not None else self.defaults.get("cache_ttl_hours", 720)
        age_hours = (time.time() - path.stat().st_mtime) / 3600.0
        if age_hours > ttl:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def save_json(self, cache_key: str, payload: Any) -> Path:
        path = self._cache_path(cache_key)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # --- logging ---------------------------------------------------------
    def log(self, status: str, message: str = "", query: str = "", url: str = "",
            records: int = 0, http_status: int | None = None, snapshot_path: str = "") -> dict[str, Any]:
        return {
            "log_id": util.new_id("log"),
            "run_id": self.run_id,
            "source_name": self.config.get("platform", self.key),
            "collector": self.key,
            "query": query,
            "url": url,
            "snapshot_path": snapshot_path,
            "observed_at": db.utcnow(),
            "status": status,
            "http_status": http_status,
            "records": records,
            "message": message,
        }

    def skip_result(self, reason: str) -> CollectResult:
        return CollectResult(logs=[self.log("skipped", message=reason)])

    # --- interface -------------------------------------------------------
    def preflight(self) -> str | None:
        """Return a skip-reason string if the collector cannot/should not run, else None."""
        if not self.enabled:
            return f"{self.key} disabled in sources.yaml"
        missing = self.missing_credentials()
        if missing:
            return f"{self.key} missing credentials: {', '.join(missing)}"
        return None

    def collect(self, products: list[dict[str, Any]]) -> CollectResult:  # pragma: no cover
        raise NotImplementedError
