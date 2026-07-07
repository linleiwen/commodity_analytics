"""Shelf-life parsing and scoring.

Parses Japanese/ISO expiration strings, computes the sellable window remaining at the
expected US return date, and maps that to a 0-1 shelf-life score (spec 9.3).
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime

_YMD = re.compile(r"(\d{4})\D{1,2}(\d{1,2})\D{1,2}(\d{1,2})")          # 2026.12.31 / 2026年12月31日
_YM = re.compile(r"(\d{4})\D{1,2}(\d{1,2})(?!\d)")                       # 2026.12  -> end of month
_DMY = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})")               # 31.12.2026


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_expiration_date(text: str | None) -> date | None:
    """Parse a variety of JP/US expiration formats. Year-month only -> last day of month."""
    if not text:
        return None
    s = str(text).strip()
    if not s:
        return None

    m = _YMD.search(s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return _safe_date(y, mo, d)

    m = _DMY.search(s)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return _safe_date(y, mo, d)

    m = _YM.search(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            last = calendar.monthrange(y, mo)[1]
            return _safe_date(y, mo, last)

    return None


def to_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    return parse_expiration_date(str(value))


def remaining_days(expiration: date | None, return_date: date) -> int | None:
    if expiration is None:
        return None
    return (expiration - return_date).days


def shelf_life_score(
    days_remaining: float | None,
    *,
    is_food: bool,
    is_cosmetic: bool,
    config: dict,
) -> tuple[float, bool]:
    """Return ``(score, hard_fail)``.

    ``hard_fail`` is True only for food whose remaining window is below the minimum
    (handled as a hard filter by the score engine). Non-food & non-cosmetic get a
    flat non-perishable score.
    """
    curve = config.get("shelf_life_curve", {})
    if not is_food and not is_cosmetic:
        return float(curve.get("non_perishable_score", 1.0)), False

    if days_remaining is None:
        # Unknown shelf life. Cosmetics tolerate it better than food.
        return (0.5 if is_cosmetic else 0.0), (False if is_cosmetic else True)

    min_food_days = config.get("hard_filters", {}).get("min_food_remaining_days", 60)
    if is_food and days_remaining < min_food_days:
        return 0.0, True

    for band in curve.get("bands", []):
        if days_remaining >= band.get("min_days", 0):
            return float(band.get("score", 0.0)), False

    # Below the lowest band but not a food hard-fail (e.g. cosmetic with short window).
    return 0.2, False
