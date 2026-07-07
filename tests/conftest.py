"""Shared pytest fixtures."""

from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def scoring_cfg():
    from app import settings

    return settings.load_config("scoring")


@pytest.fixture
def risk_cfg():
    from app import settings

    return settings.load_config("risk_rules")


@pytest.fixture
def sample_products() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "product_id": "cookie",
                "canonical_name_en": "Shiroi Koibito",
                "canonical_name_jp": "白い恋人",
                "canonical_name_cn": "白色恋人",
                "brand": "Ishiya",
                "aliases_json": '["shiroi koibito", "white lover"]',
                "jan_gtin": "4901234567890",
                "asin_us": "",
                "asin_jp": "",
            },
            {
                "product_id": "mask",
                "canonical_name_en": "LuLuLun Face Mask",
                "canonical_name_jp": "ルルルン",
                "canonical_name_cn": "LuLuLun 面膜",
                "brand": "LuLuLun",
                "aliases_json": '["lululun", "lululun mask"]',
                "jan_gtin": "",
                "asin_us": "",
                "asin_jp": "",
            },
        ]
    )
