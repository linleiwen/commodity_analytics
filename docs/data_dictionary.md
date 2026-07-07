# Data Dictionary

All tables live in the SQLite database (`data/arbitrage.sqlite`), created from
[app/storage/schema.sql](../app/storage/schema.sql). This dictionary summarizes the
decision-relevant fields; see the schema for exact column types.

## Confidence levels
Every price/demand record carries a `confidence_level`:

| Level | Score | Meaning |
| --- | --- | --- |
| `api_verified` | 1.00 | Retrieved from an official API. |
| `manual_verified` | 0.85 | Human-entered (field survey, Terapeak export). |
| `scraped_low_confidence` | 0.50 | Hand-sampled social / low-trust source. |
| `missing` | 0.20 | Absent; triggers a data-missing penalty. |

## product_master (7.1)
Canonical SKU record. Key fields: names (EN/JP/CN), `brand`, `category`,
`jan_gtin`, package geometry (`package_weight_g`, `package_*_cm`, `package_volume_liter`),
risk flags (`is_food`, `is_cosmetic`, `is_drug_or_otc_risk`, `is_hazmat_shipping_risk`),
handling risks (`melt_risk_level`, `crush_risk_level`, `leak_risk_level`), and
`category_group` (`food` | `cosmetic` | `non_food_gifts`) used by the luggage optimizer.

## price_observations (7.2)
One row per observed listing/price. `country` is `JP` or `US`; `price` is in the source
`currency`; `price_usd` is filled during `normalize`. `match_confidence` records how well
the listing maps to the product (spec 8.2). JP field-survey rows are `source_type=manual`
and are preferred for cost basis.

## demand_signals (7.3)
Social, trend, and sell-through signals. `signal_kind` is `social` | `trend` |
`sell_through`. Sell-through rows carry `median_sold_price`, `sold_count`,
`sell_through_pct`, `competitor_count`, `days_to_sell` (Terapeak-style).

## compliance_reviews (7.4)
Per-product GREEN/YELLOW/RED gate with per-dimension risks (`food_safety_risk`,
`cosmetic_drug_risk`, `shipping_risk`, `labeling_risk`), per-platform posture, `food_class`,
`reason_codes_json`, and `review_status` (`auto` | `needs_review` | `blocked`).

## scores (7.5)
Final economics and ranking: net-profit breakdown, component scores (0-1), penalties,
`final_score` (0-100), `priority_tier` (`A` | `B` | `C` | `Watchlist` | `Blocked`),
luggage outputs (`recommended_qty`, `volume_used_liter`, `weight_used_lb`,
`estimated_total_profit`, `packing_notes`), and `reason_codes_json`.

## source_log
Audit trail: one row per collector attempt with `status`
(`success` | `failure` | `skipped`), `records`, and `message`.

## Manual import CSV schemas
- **field_prices**: `product_name`, `brand`, `store_name`, `store_location`,
  `purchase_date`, `price_jpy`, `tax_included_flag`, `tax_free_price_jpy`,
  `package_count`, `weight_or_size_text`, `length_cm`, `width_cm`, `height_cm`,
  `package_weight_g`, `expiry_text`, `storage_condition`, `notes`.
- **terapeak**: `product_name`, `search_term`, `median_sold_price`, `sold_count`,
  `sell_through_pct`, `avg_shipping`, `competitor_count`, `days_to_sell`, `period_days`,
  `same_pack_flag`, `notes`.
- **social_notes**: `product_name`, `platform`, `query`, `post_title`, `post_url`,
  `post_date`, `like_count`, `save_count`, `comment_count`, `view_count`,
  `buyer_intent_comment_count`, `mention_count`, `post_count`, `manual_heat_label`,
  `window_days`, `notes`.
- **google_trends**: `product_name`, `query`, `region`, `trend_value`, `trend_slope`,
  `window_days`, `manual_heat_label`, `notes`.

Rows may also use `product_id` (exact) or `jan`/`gtin` instead of `product_name`.
