"""Pydantic data models mirroring the spec's data dictionary (section 7)."""

from __future__ import annotations

from enum import Enum


class Compliance(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PriorityTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    WATCHLIST = "Watchlist"
    BLOCKED = "Blocked"


class ConfidenceLevel(str, Enum):
    API_VERIFIED = "api_verified"
    MANUAL_VERIFIED = "manual_verified"
    SCRAPED_LOW = "scraped_low_confidence"
    MISSING = "missing"


CONFIDENCE_SCORE = {
    ConfidenceLevel.API_VERIFIED: 1.0,
    ConfidenceLevel.MANUAL_VERIFIED: 0.85,
    ConfidenceLevel.SCRAPED_LOW: 0.5,
    ConfidenceLevel.MISSING: 0.2,
}


def confidence_score(level: str | ConfidenceLevel) -> float:
    try:
        return CONFIDENCE_SCORE[ConfidenceLevel(level)]
    except (ValueError, KeyError):
        return 0.5


__all__ = [
    "Compliance",
    "RiskLevel",
    "PriorityTier",
    "ConfidenceLevel",
    "CONFIDENCE_SCORE",
    "confidence_score",
]
