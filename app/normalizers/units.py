"""Unit parsing and conversion: pack counts, weight, dimensions, volume.

Handles English and Japanese/Chinese count words so field-survey text like
``"24個入"`` or ``"12 pieces"`` normalizes consistently.
"""

from __future__ import annotations

import re

GRAMS_PER_LB = 453.59237
CM3_PER_LITER = 1000.0

# Rough fallback packing density (grams per liter) when only weight is known, used to
# estimate volume for boxed snacks/cookies. Deliberately conservative (light, boxed goods).
DEFAULT_PACKING_DENSITY_G_PER_L = 350.0

_PACK_PATTERNS = [
    re.compile(r"(\d+)\s*(?:pieces?|pcs?|pack|count|ct|sheets?|masks?)", re.IGNORECASE),
    re.compile(r"(?:x|×)\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"(\d+)\s*(?:個|枚|包|袋|本|片|入)"),  # JP/CN counters
]

_WEIGHT_PATTERNS = [
    (re.compile(r"([\d,]+(?:\.\d+)?)\s*kg", re.IGNORECASE), 1000.0),
    (re.compile(r"([\d,]+(?:\.\d+)?)\s*g\b", re.IGNORECASE), 1.0),
    (re.compile(r"([\d,]+(?:\.\d+)?)\s*ml", re.IGNORECASE), 1.0),  # treat ml ~ g for liquids
]

_DIM_PATTERN = re.compile(
    r"([\d.]+)\s*(?:cm|センチ)?\s*[x×*]\s*([\d.]+)\s*(?:cm)?\s*[x×*]\s*([\d.]+)\s*cm?",
    re.IGNORECASE,
)


# Per-listing total-unit parsing (pack-size normalization, spec 8.3): content count
# (12枚入 / 24 pcs) times an optional set multiplier (×6個セット / 2 boxes).
_CONTENT_PATTERNS = [
    re.compile(r"(\d+)\s*(?:枚|個|本|袋|包|粒|食)\s*入?り?"),
    re.compile(r"(\d+)\s*(?:pcs?|pieces?|count|ct|sheets?|masks?)\b", re.IGNORECASE),
]
_MULTIPLIER_PATTERNS = [
    re.compile(r"[x×]\s*(\d+)\s*(?:個|箱|袋|缶)?\s*(?:セット)?(?!\s*[\d.]*\s*(?:cm|mm|g\b))", re.IGNORECASE),
    re.compile(r"(\d+)\s*(?:個|箱)セット"),
    re.compile(r"(?:set\s+of|)\s*(\d+)\s*(?:boxes|sets|bags)\b", re.IGNORECASE),
]


def parse_total_units(text: str | None) -> int | None:
    """Total sellable units in a listing title: content count x set multiplier.

    ``"白い恋人（9枚入）×6個セット"`` -> 54; ``"24 pcs"`` -> 24; unparseable -> None.
    """
    if not text:
        return None
    s = str(text)
    content = None
    for pat in _CONTENT_PATTERNS:
        m = pat.search(s)
        if m:
            try:
                v = int(m.group(1))
                if v > 0:
                    content = v
                    break
            except ValueError:
                continue
    multiplier = None
    for pat in _MULTIPLIER_PATTERNS:
        m = pat.search(s)
        if m:
            try:
                v = int(m.group(1))
                if 0 < v <= 100:  # sanity: ×2026 in a date is not a set size
                    multiplier = v
                    break
            except ValueError:
                continue
    if content and multiplier:
        return content * multiplier
    return content or multiplier


def parse_pack_count(text: str | None) -> int | None:
    if not text:
        return None
    for pat in _PACK_PATTERNS:
        m = pat.search(str(text))
        if m:
            try:
                val = int(m.group(1))
                if val > 0:
                    return val
            except ValueError:
                continue
    return None


def parse_weight_grams(text: str | None) -> float | None:
    if not text:
        return None
    s = str(text)
    for pat, factor in _WEIGHT_PATTERNS:
        m = pat.search(s)
        if m:
            num = m.group(1).replace(",", "")
            try:
                return float(num) * factor
            except ValueError:
                continue
    return None


def parse_dimensions_cm(text: str | None) -> tuple[float, float, float] | None:
    """Parse an ``L x W x H`` dimension string (cm) into a tuple."""
    if not text:
        return None
    m = _DIM_PATTERN.search(str(text))
    if not m:
        return None
    try:
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    except ValueError:
        return None


def volume_liters(length_cm, width_cm, height_cm) -> float | None:
    try:
        vals = [float(length_cm), float(width_cm), float(height_cm)]
    except (TypeError, ValueError):
        return None
    if any(v <= 0 for v in vals):
        return None
    return (vals[0] * vals[1] * vals[2]) / CM3_PER_LITER


def estimate_volume_from_weight(weight_g: float | None) -> float | None:
    """Fallback volume estimate when dimensions are unknown."""
    if not weight_g or weight_g <= 0:
        return None
    return weight_g / DEFAULT_PACKING_DENSITY_G_PER_L


def grams_to_lb(weight_g: float | None) -> float | None:
    if weight_g is None or weight_g <= 0:
        return None
    return weight_g / GRAMS_PER_LB


def resolve_volume_weight(
    *,
    volume_liter: float | None,
    length_cm: float | None,
    width_cm: float | None,
    height_cm: float | None,
    weight_g: float | None,
    unit_size_text: str | None = None,
) -> tuple[float | None, float | None, bool, bool]:
    """Best-effort resolution of (volume_liter, weight_g, volume_estimated, weight_missing).

    Preference order for volume: explicit value → dimensions → text dims → weight estimate.
    """
    vol = volume_liter
    if vol is None:
        vol = volume_liters(length_cm, width_cm, height_cm)
    if vol is None and unit_size_text:
        dims = parse_dimensions_cm(unit_size_text)
        if dims:
            vol = volume_liters(*dims)

    wt = weight_g
    if wt is None and unit_size_text:
        wt = parse_weight_grams(unit_size_text)

    volume_estimated = False
    if vol is None:
        est = estimate_volume_from_weight(wt)
        if est is not None:
            vol = est
            volume_estimated = True

    weight_missing = wt is None
    return vol, wt, volume_estimated, weight_missing
