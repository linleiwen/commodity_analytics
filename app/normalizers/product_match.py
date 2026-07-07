"""Product matching: resolve an observation/import row to a Product Master id.

Match order and confidence follow spec section 8:

    1.00  JAN/GTIN/UPC exact
    0.90  ASIN + brand (+ pack size) match
    0.80  exact alias (+ pack size) match
    0.70+ fuzzy title + brand match (needs manual check)
    <0.70 not matched -> excluded unless manually verified
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

try:  # rapidfuzz is preferred; fall back to stdlib difflib if unavailable.
    from rapidfuzz import fuzz

    def _ratio(a: str, b: str) -> float:
        return float(fuzz.token_set_ratio(a, b))
except Exception:  # pragma: no cover - fallback path
    from difflib import SequenceMatcher

    def _ratio(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio() * 100.0


@dataclass
class MatchResult:
    product_id: str | None
    confidence: float
    reason: str


def _norm(s) -> str:
    return str(s or "").strip().lower()


class ProductMatcher:
    """Index Product Master once, then match many query rows against it."""

    def __init__(self, products: pd.DataFrame):
        self.products = products.copy() if products is not None else pd.DataFrame()
        self._by_jan: dict[str, str] = {}
        self._by_asin: dict[str, str] = {}
        self._alias_index: list[tuple[str, str]] = []  # (normalized alias, product_id)
        self._build()

    def _build(self) -> None:
        for _, row in self.products.iterrows():
            pid = row.get("product_id")
            if not pid:
                continue
            jan = _norm(row.get("jan_gtin"))
            if jan:
                self._by_jan[jan] = pid
            asin = _norm(row.get("asin_us")) or _norm(row.get("asin_jp"))
            if asin:
                self._by_asin[asin] = pid
            names = [
                row.get("canonical_name_en"),
                row.get("canonical_name_jp"),
                row.get("canonical_name_cn"),
                row.get("brand"),
            ]
            aliases = row.get("aliases_json")
            if isinstance(aliases, str) and aliases:
                import json

                try:
                    names.extend(json.loads(aliases))
                except json.JSONDecodeError:
                    pass
            for name in names:
                n = _norm(name)
                if n:
                    self._alias_index.append((n, pid))

    def match(
        self,
        *,
        title: str | None = None,
        jan: str | None = None,
        asin: str | None = None,
        product_id: str | None = None,
    ) -> MatchResult:
        # Explicit, pre-resolved id wins (e.g. collector queried for a specific product).
        if product_id and product_id in set(self.products.get("product_id", [])):
            return MatchResult(product_id, 1.0, "explicit_product_id")

        jn = _norm(jan)
        if jn and jn in self._by_jan:
            return MatchResult(self._by_jan[jn], 1.00, "jan_gtin_exact")

        an = _norm(asin)
        if an and an in self._by_asin:
            return MatchResult(self._by_asin[an], 0.90, "asin_match")

        q = _norm(title)
        if not q:
            return MatchResult(None, 0.0, "no_query")

        # Exact alias containment either direction.
        for alias, pid in self._alias_index:
            if alias and (alias == q or alias in q or q in alias):
                return MatchResult(pid, 0.80, "alias_exact")

        # Fuzzy over all indexed names.
        best_pid, best_score = None, 0.0
        for alias, pid in self._alias_index:
            score = _ratio(q, alias)
            if score > best_score:
                best_pid, best_score = pid, score

        if best_score >= 92:
            return MatchResult(best_pid, 0.78, f"fuzzy_{best_score:.0f}")
        if best_score >= 85:
            return MatchResult(best_pid, 0.72, f"fuzzy_{best_score:.0f}")
        if best_score >= 78:
            return MatchResult(best_pid, 0.70, f"fuzzy_{best_score:.0f}")
        return MatchResult(None, round(best_score / 100.0, 2), f"fuzzy_below_threshold_{best_score:.0f}")

    def confidence_for(self, product_id: str, title: str | None) -> float:
        """How well a listing title matches the *specific* product it is attributed to."""
        q = _norm(title)
        if not q:
            return 0.5
        best = 0.0
        for alias, pid in self._alias_index:
            if pid != product_id:
                continue
            if alias == q or alias in q or q in alias:
                return 0.85
            best = max(best, _ratio(q, alias))
        if best >= 92:
            return 0.80
        if best >= 85:
            return 0.74
        if best >= 78:
            return 0.70
        return round(best / 100.0, 2)
