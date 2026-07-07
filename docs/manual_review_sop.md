# Manual Review SOP

This pipeline is **API-first, human-verified**. Some data cannot (and should not) be
scraped automatically. This SOP covers the human steps (spec sections 5, 12, 20).

## Golden rules
- Prefer official APIs. Never bypass CAPTCHAs, rotate proxies, or spoof fingerprints.
- For login/CAPTCHA pages use `python -m app.cli capture --url ... --label ...` (a *visible*
  browser you drive yourself); it only saves HTML + a screenshot for later review.
- Only record **public** metrics. Never store private profiles or personal data.
- Keep receipts and product photos for every purchased SKU (proof of authenticity + expiry).

## 1. Japan field-survey pricing (`field_prices`)
For each candidate SKU photograph: front, back (ingredients/spec), price tag, and the
best-by / batch code. Enter one row per SKU into
`data/manual_imports/japan_store_prices.csv` with real store price, tax-free price if
eligible, package count, dimensions (cm), weight (g), expiry text, and storage condition.
Then: `python -m app.cli manual-import --type field_prices --file <csv> --run-id <run>`.

## 2. eBay Terapeak / Product Research (`terapeak`)
For each high-priority candidate, search EN / JP / CN (romaji) names, filter to US
buyers, and export the last ~90 days. Record median sold price, sold count, avg shipping,
sell-through %, competitor count, and days-to-sell into
`data/manual_imports/terapeak.csv`. Flag whether the pack size matches your SKU.

## 3. Social heat sampling (`social_notes`)
Sample the top 20-50 public results per query (Xiaohongshu / TikTok / etc.). Record only
public counts (likes, saves, comments, views) plus an estimate of buyer-intent comments
("where to buy", "ship to DMV", "restock?"). Do not collect personal info.

## 4. Google Trends (`google_trends`)
Export relative interest for US / DC / MD / VA per keyword. Record `trend_value` (0-100)
and an approximate `trend_slope`.

## 5. Acting on the workbook
Open `Manual_Review` in the exported workbook. Each row tells you the missing field, why
it matters, and how to verify it. Resolve `Compliance (YELLOW)` rows before buying, and
treat every `RED` / `Blocked` item as **do not buy for this market test**.

## Pre-trip → in-Japan → post-return loop
1. **Before**: seed list → run pipeline → read `Manual_Review` → light local demand test.
2. **In Japan**: capture real price/expiry/dimensions/photos for A/B-tier SKUs; mark
   `do_not_buy` if price, expiry, or packaging differs from expectation.
3. **Buy**: re-import field prices → `score` → follow `Luggage_Plan`; keep all receipts.
4. **Back in the US**: declare what must be declared; list with clear expiry / condition;
   test eBay + local pickup first; log actual sales to feed the next run.
