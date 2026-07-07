"""Compliance / platform-sellability rules engine (spec section 3).

Classifies each product GREEN / YELLOW / RED from keyword lists, food sub-classification,
cosmetic-vs-drug heuristics, and shipping-hazmat triggers. This is a HARD gate: RED never
reaches purchase recommendations; YELLOW is limited and flagged for human review.

Heuristic tooling only -- NOT legal, customs, or FDA advice.
"""

from __future__ import annotations

from typing import Any

from app.models import Compliance
from app.models.score import ComplianceReview

_ORDER = {Compliance.GREEN.value: 0, Compliance.YELLOW.value: 1, Compliance.RED.value: 2}


def _worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: _ORDER.get(s, 0))


def _haystack(product: dict[str, Any]) -> str:
    parts = [
        product.get("canonical_name_en"),
        product.get("canonical_name_jp"),
        product.get("canonical_name_cn"),
        product.get("category"),
        product.get("subcategory"),
        product.get("brand"),
        product.get("notes"),
        product.get("risk_notes"),
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _matches(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw and str(kw).lower() in text]


def classify_food(text: str, rules: dict[str, Any]) -> tuple[str, str, list[str]]:
    """Return (food_class_label, compliance, reason_codes) for a food product."""
    food_cfg = rules.get("food_classes", {})
    reasons: list[str] = []

    perishable = food_cfg.get("perishable_refrigerated", {})
    hits = _matches(text, perishable.get("triggers", []))
    if hits:
        reasons.append(f"food:perishable/refrigerated({','.join(hits)})")
        return perishable.get("label", "PERISHABLE_OR_REFRIGERATED_RED"), Compliance.RED.value, reasons

    animal = food_cfg.get("animal_derived_check", {})
    hits = _matches(text, animal.get("triggers", []))
    if hits:
        reasons.append(f"food:animal_derived({','.join(hits)})")
        return animal.get("label", "ANIMAL_DERIVED_CHECK"), Compliance.YELLOW.value, reasons

    low = food_cfg.get("low_risk_shelf_stable", {})
    return low.get("label", "LOW_RISK_PACKAGED_SHELF_STABLE"), Compliance.GREEN.value, reasons


def evaluate(product: dict[str, Any], rules: dict[str, Any], run_id: str) -> ComplianceReview:
    text = _haystack(product)
    reasons: list[str] = []

    category_risk = Compliance.GREEN.value
    food_safety = Compliance.GREEN.value
    cosmetic_drug = Compliance.GREEN.value
    shipping = Compliance.GREEN.value
    labeling = Compliance.GREEN.value
    food_class = ""

    is_food = bool(product.get("is_food"))
    is_cosmetic = bool(product.get("is_cosmetic"))
    is_drug = bool(product.get("is_drug_or_otc_risk"))

    # 1) Hard RED keywords (drugs, SPF, refrigerated, alcohol, etc.).
    red_hits = _matches(text, rules.get("red_keywords", []))
    if red_hits:
        category_risk = Compliance.RED.value
        reasons.append(f"red_keyword({','.join(sorted(set(red_hits)))})")

    # 2) Drug / OTC flag from category metadata.
    if is_drug:
        cosmetic_drug = Compliance.RED.value
        reasons.append("otc_or_drug_risk_flag")

    # 3) Food sub-classification.
    if is_food:
        food_class, food_status, food_reasons = classify_food(text, rules)
        food_safety = food_status
        reasons.extend(food_reasons)
        # Missing labeling info is common for repackaged food -> flag labeling as YELLOW.
        labeling = _worst(labeling, Compliance.YELLOW.value)
        reasons.append("food:verify_label_ingredients_expiry")

    # 4) Cosmetic vs drug heuristics.
    if is_cosmetic and cosmetic_drug != Compliance.RED.value:
        yellow_cosmetic = _matches(
            text,
            ["whitening", "美白", "brightening", "medicated", "薬用", "quasi-drug",
             "医薬部外品", "serum", "essence", "精华", "mask", "面膜", "anti-aging", "retinol"],
        )
        if yellow_cosmetic:
            cosmetic_drug = Compliance.YELLOW.value
            reasons.append(f"cosmetic_review({','.join(sorted(set(yellow_cosmetic)))})")

    # 5) Generic YELLOW keywords (only escalate if not already RED overall).
    yellow_hits = _matches(text, rules.get("yellow_keywords", []))
    if yellow_hits:
        category_risk = _worst(category_risk, Compliance.YELLOW.value)
        reasons.append(f"yellow_keyword({','.join(sorted(set(yellow_hits)))})")

    # 6) Green categories keep a GREEN baseline (do not downgrade RED/YELLOW findings).
    category = str(product.get("category", "")).lower()
    if category in [c.lower() for c in rules.get("green_categories", [])] and not red_hits:
        reasons.append(f"green_category({category})")

    # 7) Shipping / HAZMAT triggers.
    hazmat_hits = _matches(text, rules.get("hazmat_keywords", []))
    if hazmat_hits:
        shipping = Compliance.RED.value
        reasons.append(f"hazmat_shipping({','.join(sorted(set(hazmat_hits)))})")

    overall = _worst(category_risk, food_safety, cosmetic_drug)

    # Platform-specific posture.
    posture = rules.get("platform_posture", {})

    def platform_risk(key: str) -> str:
        base = overall
        if is_food and not posture.get(key, {}).get("food_allowed", True):
            base = _worst(base, Compliance.RED.value)
        return base

    review_status = {
        Compliance.RED.value: "blocked",
        Compliance.YELLOW.value: "needs_review",
        Compliance.GREEN.value: "auto",
    }[overall]

    return ComplianceReview(
        run_id=run_id,
        product_id=product.get("product_id", ""),
        category_risk=category_risk,
        import_risk=_worst(food_safety, category_risk),
        platform_risk_ebay=platform_risk("ebay"),
        platform_risk_facebook=platform_risk("facebook"),
        platform_risk_nextdoor=platform_risk("nextdoor"),
        platform_risk_xhs=platform_risk("xhs"),
        labeling_risk=labeling,
        food_safety_risk=food_safety,
        cosmetic_drug_risk=cosmetic_drug,
        shipping_risk=shipping,
        food_class=food_class,
        compliance_status=overall,
        reason_codes=sorted(set(reasons)),
        review_status=review_status,
    )
