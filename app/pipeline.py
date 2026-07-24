"""Pipeline orchestration: glue between collectors, normalizers, scoring, and storage.

The CLI stays thin by delegating to these functions. Each function is idempotent per
``run_id`` (it clears the run's rows for the relevant table before rewriting them).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app import settings, util
from app.collectors.base import CollectResult
from app.collectors.ebay_browse import EbayBrowseCollector
from app.collectors.google_trends_live import GoogleTrendsLiveCollector
from app.collectors.manual_price_import import ManualImporter
from app.collectors.rakuten_ichiba import RakutenIchibaCollector
from app.collectors.reddit import RedditCollector
from app.collectors.youtube import YouTubeCollector
from app.models.product import Product
from app.normalizers import price as price_norm
from app.normalizers import units as units_norm
from app.normalizers.product_match import ProductMatcher
from app.scoring import compliance_rules, luggage_optimizer, score_engine
from app.storage import db

COLLECTORS = {
    "rakuten": RakutenIchibaCollector,
    "ebay_browse": EbayBrowseCollector,
    "reddit": RedditCollector,
    "youtube": YouTubeCollector,
    "google_trends": GoogleTrendsLiveCollector,
}


# --------------------------------------------------------------------------- seeds
def import_seeds(file_path: str | Path) -> tuple[int, list[str]]:
    data = settings.load_yaml_file(file_path)
    categories_cfg = settings.load_config("categories")
    seeds = data.get("products", data if isinstance(data, list) else [])
    messages: list[str] = []
    now = db.utcnow()
    count = 0
    with db.connect() as conn:
        for seed in seeds:
            product = Product.from_seed(seed, categories_cfg)
            if not product.canonical_name_en:
                messages.append("skipped seed without canonical_name_en")
                continue
            row = product.to_row()
            existing = conn.execute(
                "SELECT * FROM product_master WHERE product_id = ?",
                (product.product_id,),
            ).fetchone()
            if existing:
                # Re-importing seeds must not wipe enrichment (dims/weight/shelf-life
                # backfilled by field surveys or collectors): keep existing values for
                # fields the seed leaves empty.
                for k in existing.keys():
                    if row.get(k) is None and existing[k] is not None:
                        row[k] = existing[k]
            row["created_at"] = existing["created_at"] if existing else now
            row["updated_at"] = now
            db.upsert(conn, "product_master", row)
            count += 1
    return count, messages


# --------------------------------------------------------------------------- collect
def _build_matcher() -> ProductMatcher:
    return ProductMatcher(db.read_products())


def _persist_result(conn, result: CollectResult) -> tuple[int, int]:
    # Idempotency: re-running a collector/import for the same run replaces that
    # source's rows instead of duplicating them (signals would otherwise double-count).
    run_ids = {x.run_id for x in (*result.observations, *result.signals)}
    for run_id in run_ids:
        for src in {o.source_name for o in result.observations if o.run_id == run_id}:
            conn.execute("DELETE FROM price_observations WHERE run_id = ? AND source_name = ?",
                         (run_id, src))
        for src in {s.source_name for s in result.signals if s.run_id == run_id}:
            conn.execute("DELETE FROM demand_signals WHERE run_id = ? AND source_name = ?",
                         (run_id, src))
    for obs in result.observations:
        obs.observed_at = obs.observed_at or db.utcnow()
        db.upsert(conn, "price_observations", obs.to_row())
    for sig in result.signals:
        sig.observed_at = sig.observed_at or db.utcnow()
        db.upsert(conn, "demand_signals", sig.to_row())
    for update in result.product_updates:
        pid = update.get("product_id")
        db.update_product_fields(conn, pid, {k: v for k, v in update.items() if k != "product_id"})
    for log in result.logs:
        db.log_source(conn, log)
    return len(result.observations), len(result.signals)


def run_collect(sources: list[str], run_id: str) -> dict[str, Any]:
    settings.load_env()
    products = db.read_products().to_dict(orient="records")
    if not products:
        return {"error": "no products in Product Master; run import-seeds first"}
    matcher = _build_matcher()
    summary: dict[str, Any] = {"run_id": run_id, "sources": {}}
    with db.connect() as conn:
        db.ensure_run(conn, run_id)
        for name in sources:
            cls = COLLECTORS.get(name)
            if not cls:
                summary["sources"][name] = {"status": "unknown_source"}
                db.log_source(conn, {
                    "log_id": util.new_id("log"), "run_id": run_id, "collector": name,
                    "status": "failure", "message": f"unknown source '{name}'",
                })
                continue
            collector = cls(run_id, matcher=matcher)
            result = collector.collect(products)
            n_obs, n_sig = _persist_result(conn, result)
            statuses = [log.get("status") for log in result.logs]
            summary["sources"][name] = {
                "observations": n_obs,
                "signals": n_sig,
                "status": "skipped" if statuses and all(s == "skipped" for s in statuses) else "ran",
            }
    return summary


def run_manual_import(manual_type: str, file_path: str | Path, run_id: str) -> dict[str, Any]:
    products = db.read_products()
    if products.empty:
        return {"error": "no products in Product Master; run import-seeds first"}
    matcher = ProductMatcher(products)
    importer = ManualImporter(run_id, manual_type, matcher)
    result = importer.import_file(file_path)
    with db.connect() as conn:
        db.ensure_run(conn, run_id)
        n_obs, n_sig = _persist_result(conn, result)
    return {
        "run_id": run_id,
        "type": manual_type,
        "observations": n_obs,
        "signals": n_sig,
        "product_updates": len(result.product_updates),
        "logs": [log["message"] for log in result.logs],
    }


# --------------------------------------------------------------------------- normalize
def run_normalize(run_id: str) -> dict[str, Any]:
    settings.load_env()
    jpy_rate = settings.jpy_to_usd_rate()
    products = db.read_products()
    matcher = ProductMatcher(products)
    obs = db.read_table("price_observations", run_id)
    updated = 0
    with db.connect() as conn:
        # Backfill product volume from dimensions where still missing.
        for p in products.to_dict(orient="records"):
            if p.get("package_volume_liter") in (None, 0) and p.get("package_length_cm"):
                vol = units_norm.volume_liters(
                    p.get("package_length_cm"), p.get("package_width_cm"), p.get("package_height_cm")
                )
                if vol:
                    db.update_product_fields(conn, p["product_id"], {"package_volume_liter": vol})

        for row in obs.to_dict(orient="records"):
            price_usd = price_norm.landed_jp_cost_usd(
                row.get("price"),
                row.get("currency"),
                tax_included=row.get("sales_tax_included_flag"),
                tax_free_eligible=row.get("tax_free_eligible_flag"),
                jpy_rate=jpy_rate,
            ) if row.get("country") == "JP" else price_norm.to_usd(
                row.get("price"), row.get("currency"), jpy_rate
            )
            match_conf = row.get("match_confidence")
            if match_conf is None or (isinstance(match_conf, float) and pd.isna(match_conf)):
                match_conf = matcher.confidence_for(row.get("product_id"), row.get("listing_title"))
            conn.execute(
                "UPDATE price_observations SET price_usd = ?, match_confidence = ? WHERE observation_id = ?",
                (price_usd, match_conf, row["observation_id"]),
            )
            updated += 1
    return {"run_id": run_id, "observations_normalized": updated, "jpy_to_usd_rate": jpy_rate}


# --------------------------------------------------------------------------- score
def _assumptions(suitcase_cfg: dict, scoring_cfg: dict) -> dict[str, Any]:
    from app.normalizers.platform_fees import DEFAULT_FEES

    avail_vol, avail_wt = luggage_optimizer._available(suitcase_cfg)
    return {
        "generated_at": db.utcnow(),
        "jpy_to_usd_rate": settings.jpy_to_usd_rate(),
        "fee_assumptions": DEFAULT_FEES.as_dict(),
        "scoring_weights": scoring_cfg.get("weights", {}),
        "hard_filters": scoring_cfg.get("hard_filters", {}),
        "suitcase": {
            "trip_id": suitcase_cfg.get("trip_id"),
            "expected_us_return_date": str(suitcase_cfg.get("expected_us_return_date")),
            "available_volume_liter": round(avail_vol, 2),
            "available_weight_lb": round(avail_wt, 2),
        },
    }


def run_score(run_id: str) -> dict[str, Any]:
    scoring_cfg = settings.load_config("scoring")
    risk_cfg = settings.load_config("risk_rules")
    suitcase_cfg = settings.load_config("suitcase")

    return_raw = suitcase_cfg.get("expected_us_return_date")
    if isinstance(return_raw, date):
        return_date = return_raw
    elif isinstance(return_raw, str):
        return_date = datetime.fromisoformat(return_raw).date()
    else:
        return_date = date.today()

    products = db.read_products()
    if products.empty:
        return {"error": "no products to score"}
    observations = db.read_table("price_observations", run_id)
    signals = db.read_table("demand_signals", run_id)

    # 1) Compliance.
    compliance_reviews = [
        compliance_rules.evaluate(p, risk_cfg, run_id)
        for p in products.to_dict(orient="records")
    ]
    with db.connect() as conn:
        db.clear_run(conn, "compliance_reviews", run_id)
        now = db.utcnow()
        for cr in compliance_reviews:
            row = cr.to_row()
            row["updated_at"] = now
            db.upsert(conn, "compliance_reviews", row)
            # Reflect hazmat shipping risk back onto the product master.
            if cr.shipping_risk == "RED":
                db.update_product_fields(conn, cr.product_id, {"is_hazmat_shipping_risk": 1})

    compliance_df = db.read_table("compliance_reviews", run_id)

    # 2) Score.
    scores = score_engine.compute_scores(
        products, observations, signals, compliance_df, scoring_cfg, return_date, run_id
    )

    # 3) Luggage optimization.
    prod_by_pid = {p["product_id"]: p for p in products.to_dict(orient="records")}
    comp_by_pid = {c["product_id"]: c for c in compliance_df.to_dict(orient="records")}
    scores, plan = luggage_optimizer.optimize(scores, prod_by_pid, comp_by_pid, suitcase_cfg)

    with db.connect() as conn:
        db.clear_run(conn, "scores", run_id)
        for s in scores:
            db.upsert(conn, "scores", s.to_row())
        db.set_run_assumptions(conn, run_id, json.dumps(_assumptions(suitcase_cfg, scoring_cfg), ensure_ascii=False))

    tiers = pd.Series([s.priority_tier for s in scores]).value_counts().to_dict()
    return {
        "run_id": run_id,
        "products_scored": len(scores),
        "tiers": tiers,
        "plan": {
            "distinct_skus": plan.distinct_skus,
            "estimated_total_profit_usd": plan.total_estimated_profit,
            "volume_used_liter": plan.volume_used_liter,
            "available_volume_liter": plan.available_volume_liter,
            "weight_used_lb": plan.weight_used_lb,
            "available_weight_lb": plan.available_weight_lb,
        },
    }
