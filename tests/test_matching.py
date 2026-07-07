"""Product matching tests (spec section 8)."""

from __future__ import annotations

from app.normalizers.product_match import ProductMatcher


def test_jan_exact_match_wins(sample_products):
    m = ProductMatcher(sample_products)
    res = m.match(jan="4901234567890", title="totally different text")
    assert res.product_id == "cookie"
    assert res.confidence == 1.00


def test_alias_exact_match(sample_products):
    m = ProductMatcher(sample_products)
    res = m.match(title="shiroi koibito")
    assert res.product_id == "cookie"
    assert res.confidence >= 0.80


def test_fuzzy_match_band(sample_products):
    m = ProductMatcher(sample_products)
    res = m.match(title="Lululun facial sheet mask 7p")
    assert res.product_id == "mask"
    assert res.confidence >= 0.70


def test_unrelated_title_not_matched(sample_products):
    m = ProductMatcher(sample_products)
    res = m.match(title="Nintendo Switch OLED console")
    assert res.product_id is None
    assert res.confidence < 0.70


def test_explicit_product_id_trusted(sample_products):
    m = ProductMatcher(sample_products)
    res = m.match(product_id="mask", title="anything")
    assert res.product_id == "mask"
    assert res.confidence == 1.0


def test_confidence_for_specific_product(sample_products):
    m = ProductMatcher(sample_products)
    assert m.confidence_for("cookie", "shiroi koibito 18 pieces") >= 0.80
    assert m.confidence_for("cookie", "unrelated widget") < 0.70
