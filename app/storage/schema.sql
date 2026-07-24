-- Japan -> DMV Arbitrage Analytics: SQLite schema.
-- Mirrors the data models in spec section 7. Safe to run repeatedly (IF NOT EXISTS).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Pipeline run metadata
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    updated_at       TEXT,
    notes            TEXT,
    assumptions_json TEXT
);

-- ---------------------------------------------------------------------------
-- 7.1 Product Master
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_master (
    product_id             TEXT PRIMARY KEY,
    canonical_name_en      TEXT,
    canonical_name_jp      TEXT,
    canonical_name_cn      TEXT,
    brand                  TEXT,
    category               TEXT,
    subcategory            TEXT,
    jan_gtin               TEXT,
    asin_us                TEXT,
    asin_jp                TEXT,
    ebay_query             TEXT,
    aliases_json           TEXT,
    package_count          INTEGER,
    unit_size_text         TEXT,
    package_weight_g       REAL,
    package_length_cm      REAL,
    package_width_cm       REAL,
    package_height_cm      REAL,
    package_volume_liter   REAL,
    is_food                INTEGER DEFAULT 0,
    is_cosmetic            INTEGER DEFAULT 0,
    is_drug_or_otc_risk    INTEGER DEFAULT 0,
    is_hazmat_shipping_risk INTEGER DEFAULT 0,
    storage_condition      TEXT,
    melt_risk_level        TEXT,
    crush_risk_level       TEXT,
    leak_risk_level        TEXT,
    limited_edition_flag   INTEGER DEFAULT 0,
    discovery_only_flag    INTEGER DEFAULT 0,  -- brand/category-level seed: rank context only, never a buy row
    category_group         TEXT,
    default_shelf_life_days INTEGER,
    risk_notes             TEXT,
    notes                  TEXT,
    created_at             TEXT,
    updated_at             TEXT
);

-- ---------------------------------------------------------------------------
-- 7.2 Price Observation
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_observations (
    observation_id        TEXT PRIMARY KEY,
    run_id                TEXT,
    product_id            TEXT,
    source_name           TEXT,
    source_type           TEXT,          -- api | manual | browser | third_party
    source_url            TEXT,
    source_snapshot_path  TEXT,
    observed_at           TEXT,
    country               TEXT,          -- JP | US
    platform              TEXT,
    listing_title         TEXT,
    listing_id            TEXT,
    seller_name_hash      TEXT,
    condition             TEXT,
    currency              TEXT,
    price                 REAL,
    shipping_price        REAL,
    sales_tax_included_flag INTEGER,
    tax_free_eligible_flag  INTEGER,
    availability_status   TEXT,
    quantity_available    INTEGER,
    rating                REAL,
    review_count          INTEGER,
    expiration_date_text  TEXT,
    expiration_date_parsed TEXT,
    price_usd             REAL,          -- normalized (filled during `normalize`)
    match_confidence      REAL,
    confidence_level      TEXT,          -- api_verified | manual_verified | scraped_low_confidence | missing
    confidence_score      REAL,
    raw_payload_path      TEXT
);
CREATE INDEX IF NOT EXISTS idx_price_obs_product ON price_observations(product_id, run_id);
CREATE INDEX IF NOT EXISTS idx_price_obs_country ON price_observations(country, platform);

-- ---------------------------------------------------------------------------
-- 7.3 Social / Demand Signal
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS demand_signals (
    signal_id            TEXT PRIMARY KEY,
    run_id               TEXT,
    product_id           TEXT,
    source_name          TEXT,
    query                TEXT,
    source_url           TEXT,
    observed_at          TEXT,
    window_days          INTEGER,
    mention_count        INTEGER,
    post_count           INTEGER,
    view_count           INTEGER,
    like_count           INTEGER,
    save_count           INTEGER,
    comment_count        INTEGER,
    share_count          INTEGER,
    unique_author_count  INTEGER,
    engagement_score     REAL,
    trend_slope          REAL,
    sentiment_score      REAL,
    buyer_intent_count   INTEGER,
    manual_heat_label    TEXT,           -- low | medium | high | viral
    -- sell-through metrics (from Terapeak-style imports)
    sold_count           INTEGER,
    sell_through_pct     REAL,
    median_sold_price    REAL,
    avg_shipping         REAL,
    competitor_count     INTEGER,
    days_to_sell         REAL,
    signal_kind          TEXT,           -- social | sell_through | trend
    notes                TEXT,
    confidence_level     TEXT,
    confidence_score     REAL
);
CREATE INDEX IF NOT EXISTS idx_demand_product ON demand_signals(product_id, run_id);

-- ---------------------------------------------------------------------------
-- 7.4 Compliance Review
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance_reviews (
    review_id            TEXT PRIMARY KEY,
    run_id               TEXT,
    product_id           TEXT,
    category_risk        TEXT,           -- green | yellow | red
    import_risk          TEXT,
    platform_risk_ebay   TEXT,
    platform_risk_facebook TEXT,
    platform_risk_nextdoor TEXT,
    platform_risk_xhs    TEXT,
    labeling_risk        TEXT,
    food_safety_risk     TEXT,
    cosmetic_drug_risk   TEXT,
    shipping_risk        TEXT,
    food_class           TEXT,
    compliance_status    TEXT,           -- GREEN | YELLOW | RED (overall)
    reason_codes_json    TEXT,
    manual_reviewer      TEXT,
    review_status        TEXT,           -- auto | needs_review | verified | blocked
    review_notes         TEXT,
    updated_at           TEXT
);
CREATE INDEX IF NOT EXISTS idx_compliance_product ON compliance_reviews(product_id, run_id);

-- ---------------------------------------------------------------------------
-- 7.5 Score Table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS scores (
    score_id                   TEXT PRIMARY KEY,
    run_id                     TEXT,
    product_id                 TEXT,
    jp_cost_usd                REAL,
    us_expected_sold_price_usd REAL,
    us_expected_net_price_usd  REAL,
    expected_net_profit_usd    REAL,
    profit_margin_pct          REAL,
    profit_per_liter           REAL,
    profit_per_lb              REAL,
    price_gap_score            REAL,
    profit_density_score       REAL,
    absolute_profit_score      REAL,
    demand_heat_score          REAL,
    sell_through_score         REAL,
    shelf_life_score           REAL,
    shelf_life_days_remaining  REAL,
    supply_reliability_score   REAL,
    ops_ease_score             REAL,
    strategic_fit_score        REAL,
    base_score                 REAL,
    compliance_penalty         REAL,
    temperature_damage_penalty REAL,
    fragility_penalty          REAL,
    matching_confidence_penalty REAL,
    data_missing_penalty       REAL,
    final_score                REAL,
    recommended_qty            INTEGER,
    recommended_channel        TEXT,
    priority_tier              TEXT,      -- A | B | C | Watchlist | Blocked
    estimated_total_profit     REAL,
    volume_used_liter          REAL,
    weight_used_lb             REAL,
    packing_notes              TEXT,
    reason_codes_json          TEXT,
    data_confidence            REAL
);
CREATE INDEX IF NOT EXISTS idx_scores_product ON scores(product_id, run_id);

-- ---------------------------------------------------------------------------
-- Source log (auditability): every collector attempt
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS source_log (
    log_id        TEXT PRIMARY KEY,
    run_id        TEXT,
    source_name   TEXT,
    collector     TEXT,
    query         TEXT,
    url           TEXT,
    snapshot_path TEXT,
    observed_at   TEXT,
    status        TEXT,      -- success | failure | skipped
    http_status   INTEGER,
    records       INTEGER,
    message       TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_log_run ON source_log(run_id);
