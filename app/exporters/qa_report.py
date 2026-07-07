"""Markdown QA report (spec section 19)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.exporters import dataset
from app.storage import db


def _reason_count(scores: pd.DataFrame, code: str) -> int:
    if scores.empty:
        return 0
    n = 0
    for raw in scores["reason_codes_json"].fillna("[]"):
        try:
            if code in json.loads(raw):
                n += 1
        except json.JSONDecodeError:
            continue
    return n


def _top_table(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return "_none_\n"
    header = "| " + " | ".join(cols) + " |\n"
    sep = "| " + " | ".join("---" for _ in cols) + " |\n"
    rows = ""
    for _, r in df.iterrows():
        rows += "| " + " | ".join(str(r.get(c, "")) for c in cols) + " |\n"
    return header + sep + rows


def build_report(run_id: str) -> str:
    products = db.read_products()
    scores = db.read_table("scores", run_id)
    compliance = db.read_table("compliance_reviews", run_id)
    source_log = db.read_table("source_log", run_id)
    ranked = dataset.build_ranked(run_id)
    manual = dataset.build_manual_review(run_id)

    tier_counts = scores["priority_tier"].value_counts().to_dict() if not scores.empty else {}
    src_success = int((source_log["status"] == "success").sum()) if not source_log.empty else 0
    src_failed = int((source_log["status"] == "failure").sum()) if not source_log.empty else 0
    src_skipped = int((source_log["status"] == "skipped").sum()) if not source_log.empty else 0
    low_match = int((scores["matching_confidence_penalty"] >= 8).sum()) if not scores.empty else 0

    opportunities = ranked[ranked["Priority_Tier"] != "Blocked"].head(10) if not ranked.empty else pd.DataFrame()
    risks = pd.DataFrame()
    if not ranked.empty:
        risks = ranked[
            (ranked["Compliance_Status"] == "RED") | (ranked["Priority_Tier"] == "Blocked")
        ].head(10)
        if risks.empty:
            risks = ranked.sort_values("Data_Confidence").head(10)

    lines: list[str] = []
    lines.append(f"# QA Report — {run_id}\n")
    lines.append(f"- **run_time**: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"- **seed_products (Product Master)**: {len(products)}")
    lines.append(f"- **products_scored**: {len(scores)}")
    lines.append(f"- **A tier**: {tier_counts.get('A', 0)}")
    lines.append(f"- **B tier**: {tier_counts.get('B', 0)}")
    lines.append(f"- **C tier**: {tier_counts.get('C', 0)}")
    lines.append(f"- **Watchlist**: {tier_counts.get('Watchlist', 0)}")
    lines.append(f"- **Blocked**: {tier_counts.get('Blocked', 0)}")
    lines.append(f"- **missing_shelf_life (food watchlist)**: {_reason_count(scores, 'food_shelf_life_unknown_or_short_watchlist')}")
    lines.append(f"- **missing_volume**: {_reason_count(scores, 'missing_volume')}")
    lines.append(f"- **missing_us_sold_data**: {_reason_count(scores, 'missing_us_sold_data')}")
    lines.append(f"- **missing_jp_real_price**: {_reason_count(scores, 'missing_jp_real_price')}")
    lines.append(f"- **low_match_confidence (<0.80)**: {low_match}")
    lines.append(f"- **sources_success**: {src_success}")
    lines.append(f"- **sources_failed**: {src_failed}")
    lines.append(f"- **sources_skipped**: {src_skipped}")
    review_products = manual["Product"].nunique() if not manual.empty else 0
    lines.append(f"- **manual_review_required (distinct products)**: {review_products}\n")

    lines.append("## Top 10 Opportunities\n")
    lines.append(_top_table(
        opportunities,
        ["Rank", "Product_Name_EN", "Priority_Tier", "Final_Score",
         "Expected_Net_Profit_USD", "Recommended_Qty", "Compliance_Status"],
    ))

    lines.append("\n## Top 10 Risks / Blocked\n")
    lines.append(_top_table(
        risks,
        ["Product_Name_EN", "Priority_Tier", "Compliance_Status", "Compliance_Reason",
         "Data_Confidence"],
    ))

    lines.append("\n## Source Log Summary\n")
    if not source_log.empty:
        summary = source_log.groupby(["collector", "status"]).size().reset_index(name="count")
        lines.append(_top_table(summary, ["collector", "status", "count"]))
    else:
        lines.append("_no source activity logged_\n")

    lines.append(
        "\n---\n_This report is decision-support tooling, not legal/customs/FDA advice. "
        "Verify compliance, labeling, taxes, and platform policy before buying or selling._\n"
    )
    return "\n".join(lines)


def export_report(run_id: str, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_report(run_id), encoding="utf-8")
    return out
