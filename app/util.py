"""Small, dependency-free utility helpers shared across the pipeline."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid

_slug_strip = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    """ASCII slug suitable for stable IDs. Non-ASCII (JP/CN) collapses to a hash suffix."""
    if not text:
        return "item"
    norm = unicodedata.normalize("NFKD", text)
    ascii_text = norm.encode("ascii", "ignore").decode("ascii").lower()
    slug = _slug_strip.sub("_", ascii_text).strip("_")
    if not slug:
        # Name was entirely non-ASCII; fall back to a short stable hash.
        slug = "x" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return slug[:max_len]


def product_id_from_names(name_en: str, brand: str = "", pack: str = "") -> str:
    """Deterministic product id from name (+brand +pack) so seeds are stable across runs."""
    base = slugify(name_en or brand or "item")
    parts = [base]
    if brand:
        parts.append(slugify(brand, 20))
    if pack:
        parts.append(slugify(pack, 12))
    return "-".join(p for p in parts if p)


def new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:16]
    return f"{prefix}_{token}" if prefix else token


def stable_hash(*parts: str) -> str:
    joined = "|".join(p or "" for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def anonymize(value: str | None) -> str | None:
    """Hash a potentially-identifying string (e.g. seller name) so we never store raw PII."""
    if not value:
        return None
    return "sel_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def as_float(value, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value, default: int | None = None) -> int | None:
    f = as_float(value, None)
    return int(f) if f is not None else default


def as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}
