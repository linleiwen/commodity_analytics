"""Tests for demand-side collectors: third-party (Chinese-header) social imports and the
live Google Trends helper math. Network is never touched here."""

from __future__ import annotations

import pandas as pd

from app.collectors.google_trends_live import _heat_label, _slope
from app.collectors.manual_price_import import ManualImporter
from app.normalizers.product_match import ProductMatcher


def _matcher() -> ProductMatcher:
    return ProductMatcher(
        pd.DataFrame(
            [
                {
                    "product_id": "cookie",
                    "canonical_name_en": "Shiroi Koibito",
                    "canonical_name_cn": "白色恋人",
                    "brand": "Ishiya",
                    "aliases_json": '["shiroi koibito", "white lover"]',
                    "jan_gtin": "",
                    "asin_us": "",
                    "asin_jp": "",
                }
            ]
        )
    )


def test_social_import_maps_chinese_headers(tmp_path):
    """A 千瓜/新红-style export with Chinese headers imports into one demand signal."""
    csv = tmp_path / "xhs.csv"
    csv.write_text(
        "商品,平台,关键词,点赞数,收藏数,评论数,播放量,笔记数,购买意向数,发布时间\n"
        "白色恋人,小红书,白色恋人,3200,1800,240,50000,120,35,2026-06-15\n",
        encoding="utf-8",
    )
    result = ManualImporter("t", "social_notes", _matcher()).import_file(csv)

    assert len(result.signals) == 1
    sig = result.signals[0]
    assert sig.product_id == "cookie"
    assert sig.source_name == "小红书"
    assert sig.like_count == 3200
    assert sig.save_count == 1800
    assert sig.comment_count == 240
    assert sig.view_count == 50000
    assert sig.post_count == 120
    assert sig.buyer_intent_count == 35
    assert sig.signal_kind == "social"


def test_social_import_still_accepts_english_headers(tmp_path):
    csv = tmp_path / "xhs_en.csv"
    csv.write_text(
        "product_name,platform,like_count,save_count,comment_count,manual_heat_label\n"
        "Shiroi Koibito,Xiaohongshu,3200,1800,240,high\n",
        encoding="utf-8",
    )
    result = ManualImporter("t", "social_notes", _matcher()).import_file(csv)
    assert result.signals[0].like_count == 3200
    assert result.signals[0].manual_heat_label == "high"


def test_trends_slope_and_heat_label():
    assert _slope([10, 20, 30, 40]) > 0        # rising interest
    assert _slope([40, 30, 20, 10]) < 0        # falling interest
    assert _slope([5]) == 0.0                   # too few points
    assert _heat_label(75) == "viral"
    assert _heat_label(45) == "high"
    assert _heat_label(15) == "medium"
    assert _heat_label(2) == "low"
