"""Shared dataset assembly for the Excel and QA-report exporters.

Joins scores + product master + compliance into the decision-ready ``Ranked_Products``
frame, derives price-source labels, and builds the ``Manual_Review`` action list.
"""

from __future__ import annotations

import json

import pandas as pd

from app.storage import db

TIER_ORDER = {"A": 0, "B": 1, "C": 2, "Watchlist": 3, "Blocked": 4}

# reason_code -> (Missing_Field, Why_It_Matters, How_To_Verify)
_REVIEW_MAP = {
    "missing_volume": ("Package volume", "Profit density and packing feasibility depend on volume",
                       "Measure L x W x H (cm) and add to the field_prices import"),
    "volume_estimated_from_weight": ("Package volume (estimated)", "Volume was estimated from weight; may be wrong",
                                     "Measure actual box dimensions"),
    "missing_weight": ("Package weight", "Airline weight limits and profit/lb",
                       "Weigh the package (grams) and add to field_prices"),
    "missing_us_sold_data": ("US sold price", "Net profit and sell-through are unknown without it",
                             "Export Terapeak sold data or record eBay sold comps"),
    "missing_jp_real_price": ("JP purchase price", "Cost basis is unknown",
                              "Record the real store price via the field_prices form"),
    "food_shelf_life_unknown_or_short_watchlist": (
        "Shelf life / expiration date", "Food resale window + eBay requires a clear expiration date",
        "Photograph the best-by / batch code and import the expiry"),
}


def build_ranked(run_id: str) -> pd.DataFrame:
    scores = db.read_table("scores", run_id)
    if scores.empty:
        return pd.DataFrame()
    products = db.read_products()
    compliance = db.read_table("compliance_reviews", run_id)

    df = scores.merge(products, on="product_id", how="left", suffixes=("", "_p"))
    if not compliance.empty:
        comp_cols = ["product_id", "compliance_status", "reason_codes_json", "review_status",
                     "food_class", "shipping_risk"]
        df = df.merge(compliance[comp_cols], on="product_id", how="left", suffixes=("", "_c"))

    jp_src, us_src = _source_labels(run_id)
    df["JP_Buy_Source"] = df["product_id"].map(jp_src).fillna("-")
    df["US_Sold_Price_Source"] = df["product_id"].map(us_src).fillna("-")

    def _compliance_reason(row) -> str:
        raw = row.get("reason_codes_json")
        if isinstance(raw, str) and raw:
            try:
                return "; ".join(json.loads(raw))
            except json.JSONDecodeError:
                return raw
        return ""

    df["Compliance_Reason"] = df.apply(_compliance_reason, axis=1)
    df["Pack_Size"] = df.apply(
        lambda r: str(r.get("unit_size_text") or (f"{int(r['package_count'])}-pack" if pd.notna(r.get("package_count")) else "")),
        axis=1,
    )
    df["Manual_Review_Needed"] = df["review_status"].isin(["needs_review", "blocked"]).map(
        {True: "YES", False: "no"}
    )

    df["_blocked"] = (df["priority_tier"] == "Blocked").astype(int)
    df = df.sort_values(by=["_blocked", "final_score"], ascending=[True, False]).reset_index(drop=True)
    df.insert(0, "Rank", range(1, len(df) + 1))

    def _num(col: str):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else pd.Series(dtype="float64")

    ranked = pd.DataFrame({
        "Rank": df["Rank"],
        "Priority_Tier": df["priority_tier"],
        "Final_Score": _num("final_score").round(1),
        "Product_Name_EN": df["canonical_name_en"],
        "Product_Name_JP": df["canonical_name_jp"],
        "Product_Name_CN": df["canonical_name_cn"],
        "Brand": df["brand"],
        "Category": df["category"],
        "Subcategory": df["subcategory"],
        "Pack_Size": df["Pack_Size"],
        "JAN_GTIN": df["jan_gtin"],
        "JP_Buy_Price_USD": _num("jp_cost_usd").round(2),
        "JP_Buy_Source": df["JP_Buy_Source"],
        "US_Expected_Sold_Price_USD": _num("us_expected_sold_price_usd").round(2),
        "US_Sold_Price_Source": df["US_Sold_Price_Source"],
        "Expected_Net_Profit_USD": _num("expected_net_profit_usd").round(2),
        "Profit_Margin_Pct": (_num("profit_margin_pct") * 100).round(1),
        "Profit_Per_Liter": _num("profit_per_liter").round(2),
        "Profit_Per_Lb": _num("profit_per_lb").round(2),
        "Demand_Heat_Score": _num("demand_heat_score").round(3),
        "Sell_Through_Score": _num("sell_through_score").round(3),
        "Shelf_Life_Days_Remaining": _num("shelf_life_days_remaining"),
        "Shelf_Life_Score": _num("shelf_life_score").round(2),
        "Compliance_Status": df.get("compliance_status"),
        "Compliance_Reason": df["Compliance_Reason"],
        "Platform_Recommendation": df["recommended_channel"],
        "Recommended_Qty": _num("recommended_qty"),
        "Estimated_Total_Profit": _num("estimated_total_profit").round(2),
        "Volume_Used_Liter": _num("volume_used_liter").round(3),
        "Weight_Used_Lb": _num("weight_used_lb").round(3),
        "Melt_Risk": df["melt_risk_level"],
        "Crush_Risk": df["crush_risk_level"],
        "Leak_Risk": df["leak_risk_level"],
        "Data_Confidence": _num("data_confidence").round(2),
        "Manual_Review_Needed": df["Manual_Review_Needed"],
        "Listing_Notes": df["risk_notes"],
        "Purchase_Notes": df["packing_notes"],
    })
    return ranked


def _source_labels(run_id: str) -> tuple[dict[str, str], dict[str, str]]:
    obs = db.read_table("price_observations", run_id)
    sig = db.read_table("demand_signals", run_id)
    jp_src: dict[str, str] = {}
    us_src: dict[str, str] = {}

    if not obs.empty:
        for pid, grp in obs.groupby("product_id"):
            jp = grp[grp["country"] == "JP"]
            if not jp.empty:
                if (jp["source_type"] == "manual").any():
                    jp_src[pid] = "FieldSurvey (manual)"
                else:
                    jp_src[pid] = ", ".join(sorted(jp["platform"].dropna().unique()))
            us = grp[grp["country"] == "US"]
            if not us.empty:
                us_src[pid] = ", ".join(sorted(us["platform"].dropna().unique())) + " (active, haircut)"

    if not sig.empty:
        st = sig[(sig["signal_kind"] == "sell_through") & sig["median_sold_price"].notna()]
        for pid in st["product_id"].unique():
            us_src[pid] = "eBay Terapeak (manual, sold)"
    return jp_src, us_src


def build_manual_review(run_id: str) -> pd.DataFrame:
    scores = db.read_table("scores", run_id)
    products = db.read_products()
    compliance = db.read_table("compliance_reviews", run_id)
    if scores.empty:
        return pd.DataFrame(columns=["Product", "Missing_Field", "Why_It_Matters",
                                     "How_To_Verify", "Status", "Reviewer_Notes"])
    name_by_pid = dict(zip(products["product_id"], products["canonical_name_en"]))
    comp_by_pid = {}
    if not compliance.empty:
        comp_by_pid = {r["product_id"]: r for r in compliance.to_dict(orient="records")}

    rows = []
    for s in scores.to_dict(orient="records"):
        pid = s["product_id"]
        name = name_by_pid.get(pid, pid)
        try:
            reasons = json.loads(s.get("reason_codes_json") or "[]")
        except json.JSONDecodeError:
            reasons = []
        for code in reasons:
            if code in _REVIEW_MAP:
                field, why, how = _REVIEW_MAP[code]
                rows.append({
                    "Product": name, "Missing_Field": field, "Why_It_Matters": why,
                    "How_To_Verify": how, "Status": "open", "Reviewer_Notes": "",
                })
        comp = comp_by_pid.get(pid, {})
        if comp.get("review_status") in ("needs_review", "blocked"):
            try:
                creasons = json.loads(comp.get("reason_codes_json") or "[]")
            except json.JSONDecodeError:
                creasons = []
            rows.append({
                "Product": name,
                "Missing_Field": f"Compliance ({comp.get('compliance_status')})",
                "Why_It_Matters": "Platform sellability / import / labeling risk",
                "How_To_Verify": "; ".join(creasons) or "Verify labels, ingredients, platform policy; keep receipts",
                "Status": comp.get("review_status"),
                "Reviewer_Notes": "",
            })
    return pd.DataFrame(rows, columns=["Product", "Missing_Field", "Why_It_Matters",
                                       "How_To_Verify", "Status", "Reviewer_Notes"])
