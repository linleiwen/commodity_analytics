"""Product Master model (spec 7.1)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app import util
from app.models import RiskLevel


class Product(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=True)

    product_id: str = ""
    canonical_name_en: str = ""
    canonical_name_jp: str = ""
    canonical_name_cn: str = ""
    brand: str = ""
    category: str = ""
    subcategory: str = ""
    jan_gtin: str = ""
    asin_us: str = ""
    asin_jp: str = ""
    ebay_query: str = ""
    aliases: list[str] = Field(default_factory=list)

    package_count: int | None = None
    unit_size_text: str = ""
    package_weight_g: float | None = None
    package_length_cm: float | None = None
    package_width_cm: float | None = None
    package_height_cm: float | None = None
    package_volume_liter: float | None = None

    is_food: bool = False
    is_cosmetic: bool = False
    is_drug_or_otc_risk: bool = False
    is_hazmat_shipping_risk: bool = False

    storage_condition: str = "ambient"
    melt_risk_level: str = RiskLevel.LOW.value
    crush_risk_level: str = RiskLevel.LOW.value
    leak_risk_level: str = RiskLevel.LOW.value
    limited_edition_flag: bool = False

    category_group: str = "non_food_gifts"
    default_shelf_life_days: int | None = None
    risk_notes: str = ""
    notes: str = ""

    @classmethod
    def from_seed(cls, seed: dict[str, Any], category_cfg: dict[str, Any]) -> "Product":
        """Build a Product from a seeds-YAML entry, applying category defaults."""
        category = seed.get("category", "")
        cats = category_cfg.get("categories", {})
        defaults = cats.get(category, category_cfg.get("default_category", {}))

        name_en = seed.get("canonical_name_en", "")
        pid = util.product_id_from_names(name_en, seed.get("brand", ""))

        return cls(
            product_id=pid,
            canonical_name_en=name_en,
            canonical_name_jp=seed.get("canonical_name_jp", ""),
            canonical_name_cn=seed.get("canonical_name_cn", ""),
            brand=seed.get("brand", ""),
            category=category,
            subcategory=seed.get("subcategory", ""),
            jan_gtin=str(seed.get("jan_gtin", "") or ""),
            ebay_query=seed.get("ebay_query", name_en),
            aliases=list(seed.get("aliases", []) or []),
            is_food=bool(defaults.get("is_food", False)),
            is_cosmetic=bool(defaults.get("is_cosmetic", False)),
            is_drug_or_otc_risk=bool(defaults.get("is_drug_or_otc_risk", False)),
            storage_condition=defaults.get("default_storage", "ambient"),
            melt_risk_level=defaults.get("default_melt_risk", RiskLevel.LOW.value),
            crush_risk_level=defaults.get("default_crush_risk", RiskLevel.LOW.value),
            leak_risk_level=defaults.get("default_leak_risk", RiskLevel.LOW.value),
            category_group=defaults.get("group", "non_food_gifts"),
            default_shelf_life_days=defaults.get("default_shelf_life_days"),
            risk_notes=seed.get("risk_notes", ""),
        )

    def to_row(self) -> dict[str, Any]:
        row = self.model_dump()
        row["aliases_json"] = json.dumps(self.aliases, ensure_ascii=False)
        row.pop("aliases", None)
        for flag in (
            "is_food",
            "is_cosmetic",
            "is_drug_or_otc_risk",
            "is_hazmat_shipping_risk",
            "limited_edition_flag",
        ):
            row[flag] = int(bool(row.get(flag)))
        # created_at / updated_at timestamps are set by the caller (seed importer).
        return row

    def search_terms(self) -> list[str]:
        """De-duplicated list of query strings for collectors."""
        terms = [
            self.canonical_name_en,
            self.canonical_name_jp,
            self.canonical_name_cn,
            *self.aliases,
        ]
        seen: list[str] = []
        for t in terms:
            t = (t or "").strip()
            if t and t.lower() not in {s.lower() for s in seen}:
                seen.append(t)
        return seen
