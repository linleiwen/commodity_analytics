# 日本商品 DMV 小批量转售 Market Test：选品分析与数据采集项目规格书

**版本**: v1.0  
**日期**: 2026-07-07  
**目标用户**: DMV 地区创业者，用 1.5 个行李箱空间从日本带回商品，验证在 eBay、Facebook Marketplace、小红书、Nextdoor 等渠道的小批量转售需求。  
**交付目标**: coding agent 按此规格搭建一个“API 优先、半自动抓取、人工验证兜底”的 analytics pipeline，最终输出一个 Excel workbook，按 SKU 排序推荐采购清单、价格、利润、风险、保质期、行李箱装载建议。

> 重要提示：此文档是商业与技术规格，不是法律、税务、海关或 FDA 合规意见。实际带货和销售前，应对入境申报、食品/化妆品/药品分类、标签、销售税、平台政策做人工确认。项目系统应把“合规/平台可售性”作为硬性过滤项，而不是事后备注。

---

## 1. 创业判断：这不是单纯爬价格，而是“旅行零售套利 + 本地稀缺品验证”

你的核心假设是：

1. DMV 地区一等一亚洲/日本热门商品供给不足，很多线下货源不是最新或不是热门版本。
2. 美国本地线上/线下售价与日本购买价存在明显价差，且差价足以覆盖平台费、运费、包装、税费、损耗、时间成本和合规风险。
3. 社交媒体热度可以提前提示“买家愿意为便利、稀缺、正品、现货支付溢价”。
4. 行李箱空间是稀缺资源，所以选品应该优先看 **单位体积/重量利润**，不是只看毛利率。

因此，本项目不应只做“爬虫”。更准确地说，应做一个 **Product Opportunity Intelligence Pipeline**：

- 价格侧：日本采购价、美国可实现成交价、平台费、运费、税费、行李箱空间成本。
- 需求侧：社交热度、eBay 成交量、Amazon/Keepa 价格稳定性、Google Trends、Reddit/YouTube/TikTok/小红书讨论。
- 风险侧：进口合规、平台政策、保质期、标签、温度/破损、品牌/灰市风险。
- 执行侧：最终不是“越多 SKU 越好”，而是用行李箱做一个受约束的组合优化。

---

## 2. 必须新增的选品维度

你原来的三个维度很好：

1. `价差 / 体积`
2. `伴手礼热度，包括美妆、护肤`
3. `保质期至少 2 个月以上，越长越加分`

建议新增以下维度，并在系统里建模：

### 2.1 净利润密度，而不是裸价差密度

裸价差容易误导。应计算：

```text
expected_net_profit_usd = expected_us_sold_price
                        - jp_purchase_cost_usd
                        - platform_fee_usd
                        - payment_fee_usd
                        - expected_shipping_subsidy_usd
                        - packaging_cost_usd
                        - customs_duty_allocated_usd
                        - sales_tax/admin_allocated_usd
                        - damage_return_allowance_usd
                        - suitcase_space_cost_usd
```

然后计算：

```text
profit_per_liter = expected_net_profit_usd / package_volume_liter
profit_per_lb    = expected_net_profit_usd / package_weight_lb
profit_density   = min-max or percentile normalized profit_per_liter
```

需要同时看 `profit_per_liter` 和 `absolute_profit`。一个体积极小但只赚 $0.80 的商品，不一定值得占用 listing、客服和交付成本。

### 2.2 Sell-through / 流动性

只看 Amazon/eBay 当前挂价不够。需要尽量抓：

- eBay sold/completed listings 的成交价与成交数量。
- eBay Product Research/Terapeak 的 sell-through、平均成交价、卖家数、趋势。
- Amazon/Keepa 的价格历史、是否长期缺货或价格异常。
- 美国本地同款 listing 数量：listing 少但需求高是机会；listing 多且卖不动是陷阱。

### 2.3 合规与平台可售性

对于食品、化妆品、护肤品，这是第一优先级。系统中应有 `compliance_status`：

- `GREEN`: 低风险，普通非食品/非药品/非危险品，或资料完整的常温稳定包装食品。
- `YELLOW`: 可考虑，但需要人工确认标签、成分、平台政策、运输规则。
- `RED`: 不建议本次 market test，包括药品、OTC、很多 sunscreen/SPF 产品、处方/医疗宣称产品、酒精、CBD/THC、鲜食、冷藏/冷冻、含肉类/高动物源风险、不清楚成分或没有原包装的食品。

硬性规则：`RED` 不进入采购推荐；`YELLOW` 限量且必须人工验证。

### 2.4 保质期的真实可售窗口

不是“产品标称保质期 > 2 个月”就够。应计算：

```text
remaining_days_at_return = expiration_date - expected_us_return_date
required_days = 60 + expected_sell_through_days + return_buffer_days
```

建议默认：

- 食品硬性门槛：回美当天剩余 >= 90 天更稳；最低 60 天。
- 美妆/护肤：未开封 shelf life 通常更长，但要看 PAO、批号、生产日期；含活性成分、SPF、药品宣称的归 YELLOW/RED。
- eBay 食品 listing 需要清楚写 expiration date。

### 2.5 温度、破损、重量与运输限制

日本热门伴手礼里巧克力、夹心饼干、玻璃瓶、液体很多。DMV 七月底/八月高温，必须扣分：

- `melt_risk`: chocolate、cream、soft candy 夏季高风险。
- `crush_risk`: 薯条类、薄饼类盒装易碎。
- `leak_risk`: 液体护肤品、油类、瓶罐。
- `shipping_hazmat_risk`: 香水、喷雾、指甲油、含酒精/气溶胶产品可能触发 USPS HAZMAT 规则。
- `weight_density`: 太重但利润不够高的 SKU 不适合行李箱套利。

### 2.6 正品证明与买家信任

本地高价转售的一个核心卖点是“日本现货、正品、带票/可拍采购小票”。系统输出要提醒：

- 是否需要保存收据。
- 是否需要拍摄店铺/收据/商品封口照片。
- 是否建议打包成礼盒/套装出售。
- 是否要在 listing 中避免“官方授权”“治疗功效”等风险措辞。

### 2.7 季节性、限定款、补货难度

日本商品往往有季节限定、地区限定、机场限定。系统应记录：

- `limited_edition`: 是否限定。
- `seasonality`: 樱花、夏季、冬季、节日礼盒。
- `restock_reliability`: 下次去日本或找代购是否能补货。
- `bundle_potential`: 是否适合和同品牌/同主题 SKU 打包卖。

---

## 3. 合规基线：系统必须内置的风险规则

### 3.1 旅客带货入境：如准备转售，不要当作个人免税物品处理

CBP 对个人免税额度的说明强调，免税物品应为个人/家庭使用或礼物，并且需要申报；法规也明确个人/家庭用品免税不适用于 business/commercial use。系统不需要替用户判断法律结论，但必须提醒：**所有食品/农产品和准备出售的商品都应如实申报，保留收据，必要时咨询 CBP/customs broker。**

### 3.2 食品：FDA/USDA/CBP 与平台要求同时存在

关键规则：

- FDA 要求进口或拟进口到美国的人/动物食品提供 Prior Notice。
- FDA 说明，进口食品通常可在没有 FDA 预先批准单个产品的情况下进口，但相关设施注册、prior notice 等要求必须满足。
- USDA/APHIS 和 CBP 对肉类、鲜果蔬、种子、土壤、动植物来源产品有额外限制；旅客进入美国要申报农业/食品类物品。
- 食品标签、营养成分、过敏原、成分表等要求也会影响“能不能正式卖”。
- eBay 食品 listing 要求安全包装、清楚标注 expiration date，并确保买家在过期前收到。

本项目策略：

- MVP 阶段把食品分成 `LOW_RISK_PACKAGED_SHELF_STABLE`、`ANIMAL_DERIVED_CHECK`、`PERISHABLE_OR_REFRIGERATED_RED`。
- 有肉、鲜奶油、冷藏/冷冻、鲜果、无商业包装或标签不清的食品直接 `RED`。
- 巧克力/奶制品饼干不一定都禁止，但需要保留原包装、成分、产地、保质期，并人工查 APHIS/CBP/FDA；高温融化风险单独扣分。

### 3.3 美妆/护肤：重点避开“在美国被当成药”的品

美国把 sunscreen/SPF 作为药品监管；FDA 也按 intended use 区分 cosmetics、drugs 或两者兼具。日本很多“医药部外品”“美白”“祛痘”“防晒”在美国销售时可能触发 OTC drug 或更复杂标签/注册问题。

MVP 建议：

- `GREEN`: 普通彩妆、普通非 SPF、非治疗宣称、非处方、非药品类工具/配件。
- `YELLOW`: 面膜、精华、护肤品，尤其含强功效宣称或英文标签不完整者。
- `RED`: sunscreen/SPF、防晒喷雾、眼药水、止痛/感冒/消炎/祛痘药、含药宣称产品、膳食补充剂。

### 3.4 平台规则

- eBay：食品可售但受限制，必须符合食品政策、过期日说明、安全包装等要求。
- Nextdoor：要求遵守本地法律，禁止受监管/有健康安全风险/违法商品。
- Facebook Marketplace/小红书/社群交易：即使实际有人卖，也不代表合规；系统应输出 `platform_allowed_confidence` 而不是默认可售。

### 3.5 税务与本地经营

market test 也可能触发：

- 销售税/使用税记录。
- Marketplace facilitator 代收税与个人线下交易的区别。
- 收入记录、成本凭证、库存记录。
- DC/MD/VA 具体要求。

MVP 不需要自动报税，但 Excel 要有 `tax_notes`、`channel_tax_handling`、`receipt_required` 字段。

---

## 4. 数据源设计

### 4.1 日本采购价数据源

优先级从高到低：

1. **手动实地采集**：Don Quijote、机场免税、百货店、药妆店、品牌店、便利店。用手机表单拍照 + 录入价格、税、包装尺寸、重量、保质期。这是最可靠的真实采购价。
2. **Rakuten Ichiba API**：关键词/JAN/品牌搜索，可取日本线上价格、店铺、库存、评价。
3. **Yahoo! Shopping Japan API**：商品搜索、关键词排名、评论等；注意官方频率限制。
4. **Amazon Japan / Keepa / PA-API**：用于线上价格和历史价，不一定代表你线下能买到。
5. **品牌官网/机场 duty-free 官网/百货官网**：用于官方价格、规格、保质期说明、限定款。
6. **Kakaku/价格比较站**：如没有合规 API，放到 manual review 或第三方数据服务，不建议强爬。

### 4.2 美国可实现售价与竞争数据源

1. **eBay Browse API**：当前 active listing，价格、shipping、seller、condition、图片。
2. **eBay Product Research/Terapeak**：成交价、sell-through、平均 shipping、卖家数、趋势。优先通过人工导出 CSV 或 Seller Hub 手动下载，再导入系统。
3. **Amazon PA-API / Keepa**：当前价、历史价、Buy Box、第三方卖家、价格稳定性。
4. **Walmart / Yamibuy / Weee / H Mart / 99 Ranch / local Asian grocery online**：作为美国现货替代品价格参考；如果无 API，采用手动/浏览器采集。
5. **Facebook Marketplace / Nextdoor**：更适合作为本地价格验证和实测销售渠道，抓取要保守，优先人工搜索与手动记录。
6. **小红书/微信群/本地华人群**：不能只抓公开数据，还要做实际 demand test：投票、pre-interest form、评论询价。

### 4.3 伴手礼/美妆热度数据源

建议按人群分层：

**中文人群**

- 小红书：关键词搜索，记录笔记数量、近期笔记、点赞/收藏/评论、爆文标题、评论痛点。
- 抖音/快手/Bilibili/微博：日本旅游购物、药妆店 haul、伴手礼榜单。
- 微信群/华人本地群：人工记录询价和预订意向。

**英语/外国人游客与美国消费者**

- TikTok：`Japan haul`, `Don Quijote haul`, `Japanese snacks`, `Japan souvenirs`, `Japanese skincare`。
- Instagram/Reels/Threads：旅游购物和美妆关键词；Meta 官方 API 对公开搜索不一定满足需求，MVP 以人工/第三方工具为主。
- YouTube Data API：日本旅游购物视频、haul、top souvenirs。
- Reddit Data API：r/JapanTravel、r/AsianBeauty、r/snackexchange、r/AskAnAmerican、地方 subreddit。
- Google Trends：按 US、DC、Maryland、Virginia 做关键词相对热度；官方 Trends API 目前是 alpha/申请制，MVP 可手动导出或用第三方/pytrends 作为辅助。
- Pinterest/博客/listicles/Tripadvisor：用来发现候选 SKU，不直接作为成交需求证据。

### 4.4 不建议直接强爬的平台

- 小红书、Instagram/Threads、Facebook Marketplace、Nextdoor、TikTok：反爬强、登录态复杂、ToS/隐私风险高。
- Amazon/eBay active listing 可以优先 API；sold data 用 Terapeak 人工导出更稳。
- 对这些平台采用：`manual_browser_capture`、`CSV import`、`third_party_export`、`screenshot/photo evidence`。

---

## 5. 数据采集原则：API 优先、低频、人工验证、可审计

### 5.1 不做的事情

coding agent 不应实现：

- 验证码绕过。
- 代理池、住宅代理、指纹伪装、反封号规避。
- 抓取私密群组、非公开个人信息、买家/卖家个人资料。
- 高频访问或无缓存重复请求。
- 用虚假账号批量抓取。

### 5.2 应做的事情

- 官方 API 优先。
- 有登录/CAPTCHA 的页面用 headed browser + 用户手动操作 + 保存快照，不自动绕过。
- 每月运行一次，所有请求限速、缓存、记录 source log。
- 所有非 API 页面保存 HTML/screenshot/path/timestamp，便于人工复查。
- 对关键字段设置 `data_confidence`：`api_verified`、`manual_verified`、`scraped_low_confidence`、`missing`。

---

## 6. 系统架构

### 6.1 推荐技术栈

- Python 3.11+
- `httpx` / `requests`: API 调用
- `pydantic`: 数据模型与校验
- `pandas`: 数据处理
- `duckdb` 或 `sqlite`: 本地分析数据库
- `playwright`: 低频浏览器自动化与手动验证流程
- `beautifulsoup4` / `selectolax`: HTML 解析
- `rapidfuzz`: 商品名模糊匹配
- `openpyxl` 或 `xlsxwriter`: Excel 输出
- `typer` 或 `click`: CLI
- `pytest`: 测试
- optional: `sentence-transformers` / OpenAI-compatible embeddings for product matching，MVP 可先不用

### 6.2 Repo 结构

```text
japan-dmv-arbitrage/
  README.md
  .env.example
  pyproject.toml
  Makefile
  config/
    sources.yaml
    scoring.yaml
    categories.yaml
    risk_rules.yaml
    keyword_seeds.yaml
    suitcase.yaml
  data/
    raw/
    snapshots/
    manual_imports/
    processed/
    exports/
  app/
    __init__.py
    cli.py
    models/
      product.py
      observation.py
      social.py
      score.py
    collectors/
      base.py
      ebay_browse.py
      ebay_terapeak_import.py
      amazon_paapi.py
      keepa.py
      rakuten_ichiba.py
      yahoo_jp_shopping.py
      reddit.py
      youtube.py
      google_trends_import.py
      manual_price_import.py
      browser_capture.py
    normalizers/
      price.py
      units.py
      product_match.py
      shelf_life.py
      platform_fees.py
    scoring/
      score_engine.py
      compliance_rules.py
      luggage_optimizer.py
    exporters/
      excel.py
      qa_report.py
    storage/
      db.py
      schema.sql
  tests/
    test_units.py
    test_scoring.py
    test_matching.py
    test_export_excel.py
  docs/
    data_dictionary.md
    manual_review_sop.md
```

### 6.3 CLI 命令

```bash
# 初始化数据库
python -m app.cli init-db

# 导入候选 SKU / 关键词
python -m app.cli import-seeds --file config/keyword_seeds.yaml

# 采集 API 数据
python -m app.cli collect --sources rakuten,yahoo_jp,ebay_browse,reddit,youtube --run-id 2026-07-japan-trip

# 导入人工导出的 Terapeak / Google Trends / 小红书记录
python -m app.cli manual-import --type terapeak --file data/manual_imports/terapeak.csv --run-id 2026-07-japan-trip
python -m app.cli manual-import --type social_notes --file data/manual_imports/xhs_notes.csv --run-id 2026-07-japan-trip
python -m app.cli manual-import --type field_prices --file data/manual_imports/japan_store_prices.csv --run-id 2026-07-japan-trip

# 运行匹配、归一化、评分
python -m app.cli normalize --run-id 2026-07-japan-trip
python -m app.cli score --run-id 2026-07-japan-trip

# 输出 Excel
python -m app.cli export-xlsx --run-id 2026-07-japan-trip --out data/exports/japan_dmv_product_rankings.xlsx

# 输出 QA 报告
python -m app.cli qa-report --run-id 2026-07-japan-trip --out data/exports/qa_report.md
```

---

## 7. 数据模型

### 7.1 Product Master

```text
product_id
canonical_name_en
canonical_name_jp
canonical_name_cn
brand
category
subcategory
jan_gtin
asin_us
asin_jp
ebay_query
aliases_json
package_count
unit_size_text
package_weight_g
package_length_cm
package_width_cm
package_height_cm
package_volume_liter
is_food
is_cosmetic
is_drug_or_otc_risk
is_hazmat_shipping_risk
storage_condition
melt_risk_level
crush_risk_level
leak_risk_level
limited_edition_flag
notes
created_at
updated_at
```

### 7.2 Price Observation

```text
observation_id
run_id
product_id
source_name
source_type              # api, manual, browser, third_party
source_url
source_snapshot_path
observed_at
country                  # JP, US
platform                 # Rakuten, YahooJP, eBay, AmazonUS, Keepa, HMart, etc.
listing_title
listing_id
seller_name_hash         # optional; avoid storing unnecessary PII
condition
currency
price
shipping_price
sales_tax_included_flag
tax_free_eligible_flag
availability_status
quantity_available
rating
review_count
expiration_date_text
expiration_date_parsed
confidence_score
raw_payload_path
```

### 7.3 Social / Demand Signal

```text
signal_id
run_id
product_id
source_name              # Xiaohongshu, TikTok, Reddit, YouTube, GoogleTrends, etc.
query
source_url
observed_at
window_days
mention_count
post_count
view_count
like_count
save_count
comment_count
share_count
unique_author_count
engagement_score
trend_slope
sentiment_score
manual_heat_label        # low, medium, high, viral
notes
confidence_score
```

### 7.4 Compliance Review

```text
review_id
run_id
product_id
category_risk            # green, yellow, red
import_risk              # green, yellow, red
platform_risk_ebay
platform_risk_facebook
platform_risk_nextdoor
platform_risk_xhs
labeling_risk
food_safety_risk
cosmetic_drug_risk
shipping_risk
reason_codes_json
manual_reviewer
review_status            # auto, needs_review, verified, blocked
review_notes
updated_at
```

### 7.5 Score Table

```text
score_id
run_id
product_id
jp_cost_usd
us_expected_sold_price_usd
us_expected_net_price_usd
expected_net_profit_usd
profit_margin_pct
profit_per_liter
profit_per_lb
price_gap_score
demand_heat_score
sell_through_score
shelf_life_score
supply_reliability_score
ops_ease_score
compliance_penalty
temperature_damage_penalty
matching_confidence_penalty
final_score
recommended_qty
recommended_channel
priority_tier             # A, B, C, Watchlist, Blocked
```

---

## 8. 商品匹配逻辑

同一个商品在日本和美国可能有不同标题、包装数量、英文名和中文名。必须避免把 12 枚装和 24 枚装、限定版和普通版混为一谈。

### 8.1 匹配顺序

1. JAN/GTIN/UPC 精确匹配。
2. ASIN/品牌官方 SKU 匹配。
3. 规格匹配：包装数量、容量、重量、口味、版本。
4. 名称 alias 匹配：英文/日文/中文/罗马音。
5. fuzzy score + 人工确认。

### 8.2 匹配置信度

```text
1.00: JAN/GTIN exact match
0.90: ASIN + brand + pack size match
0.80: exact alias + pack size match
0.70: fuzzy title + brand + category match, needs manual check
<0.70: not matched; exclude from final score unless manually verified
```

### 8.3 需要特别处理的字段

- `pack_count`: 12 pieces / 18 pieces / 24 pieces 必须拆出来。
- `flavor`: 原味、抹茶、草莓、限定口味。
- `region`: 北海道限定、东京站限定、机场限定。
- `temperature`: 常温/冷藏/冷冻。
- `expiry`: 日本日期格式、批号、赏味期限。

---

## 9. 评分模型

### 9.1 硬性过滤

一个产品只有满足以下条件才进入 `Ranked_Products`：

```text
compliance_status != RED
expected_net_profit_usd > 0
matching_confidence >= 0.70 OR manual_verified = true
if is_food: remaining_days_at_return >= 60
if shelf_life_unknown AND is_food: priority_tier = Watchlist, not Buy
if shipping_hazmat_risk = RED: local_pickup_only OR blocked
```

### 9.2 分数权重

建议 MVP 使用 0-100 分。

```text
base_score =
    0.24 * profit_density_score
  + 0.16 * absolute_profit_score
  + 0.18 * demand_heat_score
  + 0.14 * sell_through_score
  + 0.10 * shelf_life_score
  + 0.07 * supply_reliability_score
  + 0.06 * operational_ease_score
  + 0.05 * strategic_fit_score

final_score = 100 * base_score
            - compliance_penalty
            - temperature_damage_penalty
            - fragility_penalty
            - matching_confidence_penalty
            - data_missing_penalty
```

### 9.3 分数说明

**profit_density_score**

- 用 `profit_per_liter` 做 percentile rank。
- 对极端值 winsorize，避免一个异常 listing 拉高分数。

**absolute_profit_score**

- 用 `expected_net_profit_usd` 做 percentile rank。
- 低于 $3/件默认扣分，除非可 bundle。

**demand_heat_score**

综合：

```text
social_mentions_30d
social_engagement_30d
trend_slope
number_of_independent_sources
buyer_intent_terms_count  # e.g. “where to buy”, “can’t find”, “DMV”, “shipping?”
```

**sell_through_score**

综合：

```text
ebay_sold_count_90d
terapeak_sell_through
median_days_to_sell if available
amazon_offer_count and price stability
current_competitor_count
```

**shelf_life_score**

```text
if non_food_non_cosmetic: 1.0
if days_remaining >= 365: 1.0
if days_remaining >= 180: 0.85
if days_remaining >= 90: 0.60
if days_remaining >= 60: 0.35
else: hard filter out
```

**operational_ease_score**

高分特征：

- 小、轻、不易碎、不融化。
- 原包装好看，适合拍照。
- 不需要冷链。
- 不需要复杂解释。
- 买家愿意本地 pickup。

**strategic_fit_score**

高分特征：

- 能建立“日本一线热门现货”品牌心智。
- 可形成复购或套装。
- 未来可规模化补货。
- 能吸引 DMV 本地华人/日系文化消费者。

### 9.4 惩罚项建议

```text
compliance_penalty:
  GREEN = 0
  YELLOW = 10-25
  RED = block

temperature_damage_penalty:
  LOW = 0
  MEDIUM = 5-12
  HIGH = 15-30

fragility_penalty:
  LOW = 0
  MEDIUM = 5
  HIGH = 10-20

matching_confidence_penalty:
  confidence >= 0.90: 0
  0.80-0.89: 3
  0.70-0.79: 8
  <0.70: block unless manual verified

data_missing_penalty:
  missing volume: 8
  missing weight: 5
  missing shelf life for food: block/watchlist
  missing US sold data: 8
  missing JP real price: 8
```

---

## 10. 行李箱组合优化

最终不只是按 SKU 排名，还要根据 1.5 个行李箱做组合。

### 10.1 输入参数

`config/suitcase.yaml`:

```yaml
trip_id: 2026-07-japan-trip
suitcases:
  - name: checked_bag_1
    usable_volume_liter: 75
    max_weight_lb: 50
    reserved_volume_liter: 20
    reserved_weight_lb: 15
  - name: checked_bag_2_half
    usable_volume_liter: 35
    max_weight_lb: 25
    reserved_volume_liter: 10
    reserved_weight_lb: 5
business_constraints:
  max_skus: 40
  max_units_per_sku_default: 6
  max_units_per_yellow_risk_sku: 2
  min_units_per_sku_default: 1
  category_caps:
    food: 0.55
    cosmetic: 0.35
    non_food_gifts: 0.40
  diversity_bonus: true
```

### 10.2 优化目标

```text
maximize sum(quantity_i * expected_net_profit_i * confidence_i)
```

约束：

```text
sum(quantity_i * volume_i) <= available_volume
sum(quantity_i * weight_i) <= available_weight
number_of_distinct_skus <= max_skus
quantity_i <= max_units_i
YELLOW risk quantity <= configured cap
```

### 10.3 输出字段

```text
recommended_qty
estimated_total_profit
suitcase_volume_used_liter
suitcase_weight_used_lb
category_mix
risk_mix
packing_notes
```

---

## 11. Excel 输出规格

最终 workbook：`japan_dmv_product_rankings.xlsx`

### 11.1 Tab: Ranked_Products

核心决策页。字段：

```text
Rank
Priority_Tier
Final_Score
Product_Name_EN
Product_Name_JP
Product_Name_CN
Brand
Category
Subcategory
Pack_Size
JAN_GTIN
JP_Buy_Price_USD
JP_Buy_Source
US_Expected_Sold_Price_USD
US_Sold_Price_Source
Expected_Net_Profit_USD
Profit_Margin_Pct
Profit_Per_Liter
Profit_Per_Lb
Demand_Heat_Score
Sell_Through_Score
Shelf_Life_Days_Remaining
Shelf_Life_Score
Compliance_Status
Compliance_Reason
Platform_Recommendation
Recommended_Qty
Estimated_Total_Profit
Volume_Used_Liter
Weight_Used_Lb
Melt_Risk
Crush_Risk
Leak_Risk
Data_Confidence
Manual_Review_Needed
Listing_Notes
Purchase_Notes
```

条件格式：

- `Priority_Tier A`: 绿色
- `Priority_Tier B`: 蓝色/浅绿
- `Watchlist`: 黄色
- `Blocked`: 红色/灰色
- `Shelf_Life_Days_Remaining < 90`: 黄色
- `Compliance_Status = RED`: 红色
- `Data_Confidence < 0.75`: 橙色

### 11.2 Tab: Product_Master

规范化后的 SKU 主数据。

### 11.3 Tab: Price_Observations

所有价格观测，不要只保留最终值。用于追溯。

### 11.4 Tab: Demand_Signals

社交、搜索、成交、趋势数据。

### 11.5 Tab: Compliance_QA

每个 SKU 的规则触发、人工审核状态和备注。

### 11.6 Tab: Luggage_Plan

按推荐采购数量输出装箱计划。

字段：

```text
Product
Recommended_Qty
Unit_Volume_Liter
Total_Volume_Liter
Unit_Weight_Lb
Total_Weight_Lb
Packing_Risk
Packing_Instructions
```

### 11.7 Tab: Assumptions

记录所有假设：汇率、平台费、邮费、行李箱容量、损耗率、税费假设。

### 11.8 Tab: Manual_Review

需要人工补充的项目：

```text
Product
Missing_Field
Why_It_Matters
How_To_Verify
Status
Reviewer_Notes
```

### 11.9 Tab: Source_Log

记录 source、URL、时间、collector、snapshot path、success/failure。

---

## 12. 人工数据采集 SOP

### 12.1 日本实地采价表单

建议用 Google Form / Airtable / 手机表单。字段：

```text
photo_front
photo_back
photo_price_tag
photo_expiration_date
store_name
store_location
purchase_date
product_name_as_seen
brand
price_jpy
tax_included_flag
tax_free_price_jpy
package_count
weight_or_size_text
expiry_text
storage_condition
notes
```

每个候选 SKU 至少拍：正面、背面成分/规格、价格牌、保质期/批号。

### 12.2 eBay/Terapeak 手动导出

对于每个高优先级候选词：

1. 搜索英文名、日文名、中文名/罗马音。
2. 过滤 US location 或 shipped to US。
3. 导出最近 90 天或 Terapeak 可用周期。
4. 记录 median sold price、sold count、average shipping、sell-through。
5. 手动标记是否同 pack size。

### 12.3 小红书/社交热度手动采样

对每个候选产品记录前 20-50 个结果即可，不要高频抓取：

```text
query
platform
post_title
post_url
post_date
like_count
save_count
comment_count
view_count if available
author_type optional, no personal info needed
buyer_intent_comment_count manual estimate
notes
```

只记录公开指标，不采集私人资料。

---

## 13. 候选 SKU 发现逻辑

### 13.1 Seed 关键词

每个产品需要多语言 alias：

```yaml
- canonical_name_en: Shiroi Koibito
  canonical_name_jp: 白い恋人
  canonical_name_cn: 白色恋人
  aliases:
    - shiroi koibito
    - 白い恋人
    - 白色恋人
    - ishiyaseika white lover
  category: food_souvenir_cookie
```

### 13.2 候选类别建议

**食品伴手礼**

- 常温、商业包装、保质期长、体积不夸张的饼干/糖果/零食。
- 避免冷藏、鲜食、含肉类、无清晰标签、保质期短。
- 巧克力类要单独考虑夏季融化风险。

**美妆/护肤**

- 优先：彩妆、小工具、面膜、非 SPF、非药品宣称、体积小、重量轻、美国售价高。
- 避免：防晒/SPF、眼药水、药妆强功效、祛痘药、止痛/感冒药、补充剂。

**非食品礼品**

- 文具、IP 小物、Sanrio/Pokemon/Ghibli 类、限定扭蛋/盲盒。
- 优点：无保质期，合规风险通常低于食品/药品。
- 风险：品牌/IP、仿品、平台假货误判、授权描述不要乱写。

### 13.3 早期不要只买“网红爆品”

建议组合：

```text
40% 高确定性热门品：已经有 eBay sold data 和社交热度
30% 高利润密度小件：美妆/小物/限定款
20% 长尾测试品：社交有苗头但美国供给少
10% 个人判断/本地群预订品：用来学习市场
```

---

## 14. Listing 与销售实验设计

数据系统输出后，还要设计 market test：

### 14.1 渠道策略

- **eBay**：最好做价格 discovery 和全国需求测试；但费用、shipping、退货、食品政策要严格。
- **Facebook Marketplace**：适合 DMV 本地 pickup，减少 shipping；但平台政策和买家信任要管理。
- **Nextdoor**：适合邻里低频售卖、礼盒/本地 pickup；要遵守本地法律与平台政策。
- **小红书/华人群**：适合讲“日本刚带回、现货、正品、可自取”，但交易信任和社群规则要注意。

### 14.2 Listing 文案原则

- 明确：未开封、原包装、保质期、产地、购买日期。
- 不使用：治疗、改善疾病、官方授权、FDA approved 等高风险字眼。
- 食品必须标注 expiration date。
- 美妆护肤避免暗示治疗功效。
- 对有温度风险商品，优先 local pickup 或声明保存方式。

### 14.3 实验指标

系统可以在后续版本增加销售记录表：

```text
listing_date
channel
views
messages
offers
sold_price
days_to_sell
buyer_type
pickup_or_ship
refund_or_issue
actual_profit
notes
```

目标不是第一批赚最多，而是验证：

- 哪类商品询价最快。
- 哪类买家愿意溢价。
- 哪些 SKU 物流/保质期/信任成本过高。
- 哪些适合下次批量补货。

---

## 15. 爬虫不 OK 时的替代方案

### 15.1 API + 手动导出路线

这是 MVP 首选：

- eBay Browse API + Terapeak 手动导出。
- Amazon PA-API 或 Keepa。
- Rakuten/Yahoo Japan API。
- Reddit/YouTube 官方 API。
- Google Trends 手动导出或 alpha API 申请。
- 小红书/TikTok/Instagram/Threads 采用人工采样或第三方 social listening 工具导出。

优点：合规、稳定、coding 难度低。缺点：有人工步骤。

### 15.2 付费工具路线

可考虑：

- Keepa：Amazon 价格历史。
- eBay Product Research/Terapeak：eBay 成交数据。
- Jungle Scout / Helium 10：Amazon 市场数据，偏 Amazon seller 生态。
- Apify / SerpApi / SearchAPI：用于搜索结果或公开网页抓取，仍需检查 ToS 和合规。
- 小红书/抖音/社交工具：新红数据、千瓜、蝉妈妈、灰豚等，适合导出热度，不一定能直接给 SKU 级别成交。

### 15.3 完全人工但数据化路线

对于第一次日本行，可能最实际：

1. 系统先生成候选 SKU 和需要验证的字段。
2. 你在日本只负责扫码/拍照/录价/录保质期。
3. 回来后系统导入表单、Terapeak、Keepa、社交手动样本。
4. 系统输出 Excel 排名和行李箱建议。

这个路线比“强爬所有网站”更适合低频 market test。

---

## 16. Coding Agent 实现任务清单

### Milestone A: 项目骨架与 schema

Acceptance criteria:

- `python -m app.cli init-db` 创建数据库。
- `tests/test_units.py`、`tests/test_scoring.py` 可运行。
- `config/*.yaml` 可被读取并校验。

### Milestone B: 手动导入和 API collectors

先实现：

- `manual_price_import.py`
- `ebay_browse.py`
- `ebay_terapeak_import.py`
- `rakuten_ichiba.py`
- `yahoo_jp_shopping.py`
- `keepa.py` 或 stub
- `reddit.py`
- `youtube.py`

Acceptance criteria:

- 至少 10 个 seed products 能生成 price observations。
- 每条 observation 有 source、timestamp、confidence。

### Milestone C: 商品匹配与归一化

实现：

- currency conversion
- units conversion
- pack size parsing
- product alias matching
- shelf life parsing
- fee calculation

Acceptance criteria:

- 同一 SKU 不同平台能归到同一个 `product_id`。
- pack size 不同不能错误合并。

### Milestone D: 风险规则与评分

实现：

- `risk_rules.yaml`
- `compliance_rules.py`
- `score_engine.py`
- penalties
- priority tier

Acceptance criteria:

- sunscreen/SPF、OTC medicine、refrigerated food 被标为 RED 或 YELLOW/needs review。
- 食品缺保质期不进入 Buy 推荐。
- 分数可解释，每个 SKU 有 reason codes。

### Milestone E: Excel 输出

实现 `exporters/excel.py`。

Acceptance criteria:

- 输出 workbook 包含所有 tabs。
- `Ranked_Products` 有排序、条件格式、冻结首行、筛选。
- `Assumptions` 写入汇率、费用、风险权重。
- `Manual_Review` 列出所有缺失关键字段。

### Milestone F: 行李箱优化

实现简单整数优化。MVP 可用 greedy：按 `final_score * expected_profit / volume` 排序，再按约束装箱。后续可换 `ortools`。

Acceptance criteria:

- 给定 suitcase config，输出 recommended_qty。
- 不超体积、不超重量、不超过 category/risk caps。

---

## 17. 配置文件示例

### 17.1 scoring.yaml

```yaml
weights:
  profit_density: 0.24
  absolute_profit: 0.16
  demand_heat: 0.18
  sell_through: 0.14
  shelf_life: 0.10
  supply_reliability: 0.07
  operational_ease: 0.06
  strategic_fit: 0.05
penalties:
  compliance_yellow_min: 10
  compliance_yellow_max: 25
  melt_medium: 8
  melt_high: 20
  fragility_medium: 5
  fragility_high: 15
  missing_volume: 8
  missing_weight: 5
  missing_us_sold_data: 8
  missing_jp_real_price: 8
hard_filters:
  min_food_remaining_days: 60
  min_match_confidence: 0.70
  min_expected_net_profit_usd: 0.01
```

### 17.2 risk_rules.yaml

```yaml
red_keywords:
  - sunscreen
  - SPF
  - sunblock
  - eye drops
  - pain relief
  - cold medicine
  - acne treatment
  - antibiotic
  - supplement
  - CBD
  - THC
  - alcohol
  - refrigerated
  - frozen
  - fresh meat
  - jerky
  - raw egg
  - prescription

yellow_keywords:
  - whitening
  - brightening
  - medicated
  - quasi-drug
  - anti-aging
  - retinol
  - vitamin C serum
  - dairy
  - chocolate
  - cream filling
  - aerosol
  - perfume
  - nail polish

green_categories:
  - stationery
  - keychain
  - plush
  - sealed_cookie
  - hard_candy
  - makeup_tool
  - non_spf_makeup
```

---

## 18. 初始候选产品种子示例

这些只是 seed，不是采购建议；必须经过系统评分和人工验证。

```yaml
products:
  - canonical_name_en: Shiroi Koibito
    canonical_name_jp: 白い恋人
    canonical_name_cn: 白色恋人
    category: food_souvenir_cookie
    risk_notes: shelf-stable but dairy/chocolate/melt check; expiration required

  - canonical_name_en: Tokyo Banana
    canonical_name_jp: 東京ばな奈
    canonical_name_cn: 东京香蕉
    category: food_souvenir_cake
    risk_notes: shelf-life may be short; likely needs careful expiry check

  - canonical_name_en: Jaga Pokkuru
    canonical_name_jp: じゃがポックル
    canonical_name_cn: 薯条三兄弟
    category: food_souvenir_snack
    risk_notes: crush risk; good souvenir heat candidate

  - canonical_name_en: Japanese Regional KitKat Assortment
    canonical_name_jp: キットカット ご当地
    canonical_name_cn: 日本限定 KitKat
    category: food_souvenir_chocolate
    risk_notes: melt risk in summer; check price and expiry

  - canonical_name_en: LuLuLun Face Mask
    canonical_name_jp: ルルルン フェイスマスク
    canonical_name_cn: LuLuLun 面膜
    category: cosmetic_mask
    risk_notes: cosmetic labeling/manual review; avoid drug claims

  - canonical_name_en: Canmake Makeup
    canonical_name_jp: キャンメイク
    canonical_name_cn: Canmake 彩妆
    category: cosmetics_makeup
    risk_notes: generally easier than skincare; check shade demand

  - canonical_name_en: Anessa Sunscreen
    canonical_name_jp: アネッサ 日焼け止め
    canonical_name_cn: 安耐晒防晒
    category: sunscreen
    risk_notes: RED or high-risk in US because sunscreen/SPF is regulated as drug

  - canonical_name_en: Japanese Eye Drops
    canonical_name_jp: 目薬
    canonical_name_cn: 日本眼药水
    category: otc_drug
    risk_notes: RED for resale market test

  - canonical_name_en: Ghibli / Sanrio / Pokemon Small Goods
    canonical_name_jp: キャラクター雑貨
    canonical_name_cn: IP 小物
    category: non_food_gift
    risk_notes: no shelf life; watch IP/counterfeit/listing wording
```

---

## 19. QA 报告要求

每次输出 Excel，同时输出 `qa_report.md`，包含：

```text
run_id
run_time
number_of_seed_products
number_of_products_scored
number_of_A_tier
number_of_B_tier
number_of_watchlist
number_of_blocked
missing_shelf_life_count
missing_volume_count
low_match_confidence_count
sources_success_count
sources_failed_count
manual_review_required_count
top_10_opportunities
top_10_risks
```

---

## 20. 最终使用流程

### 出发前

1. 准备候选 seed list。
2. 跑 API/手动导入，生成初版 Excel。
3. 得到 `Manual_Review`：明确在日本要拍哪些产品、补哪些字段。
4. 先在本地社群做轻量需求测试：投票/询价/意向表，不收钱或明确非承诺。

### 在日本

1. 用手机表单录入真实价格、保质期、体积/重量、照片。
2. 对 A/B tier 的 SKU 优先验证。
3. 如果保质期、价格或包装与预期不符，标记 `do_not_buy`。

### 购买前

1. 重新导入 field prices。
2. 跑 `score` + `luggage_optimizer`。
3. 按 `Luggage_Plan` 采购。
4. 保留所有收据、包装、价格牌照片。

### 回美后

1. 如实申报应申报物品。
2. 拍 listing 照片，写保质期/规格/未开封。
3. 先按推荐渠道测试：eBay + local pickup。
4. 记录销售结果，反哺下一次评分。

---

## 21. 关键参考资料

- FDA Prior Notice of Imported Foods: https://www.fda.gov/industry/prior-notice-imported-foods/filing-prior-notice-imported-foods
- FDA Importing Food Products into the United States: https://www.fda.gov/food/food-imports-exports/importing-food-products-united-states
- FDA Food Labeling Guide: https://www.fda.gov/regulatory-information/search-fda-guidance-documents/guidance-industry-food-labeling-guide
- FDA Food Allergies: https://www.fda.gov/food/nutrition-food-labeling-and-critical-foods/food-allergies
- USDA APHIS Traveling With Food or Agricultural Products: https://www.aphis.usda.gov/traveling-with-ag-products
- USDA APHIS Milk, Dairy, and Egg Products: https://www.aphis.usda.gov/traveling-with-ag-products/milk-dairy-eggs
- CBP Bringing Food into the U.S.: https://www.cbp.gov/travel/international-visitors/agricultural-items
- CBP Duty-free exemption: https://www.help.cbp.gov/s/article/Article-1402?language=en_US
- eCFR 19 CFR 148.51 Personal/household articles exemption: https://www.ecfr.gov/current/title-19/chapter-I/part-148/subpart-F/section-148.51
- CBP What to Expect When You Return: https://www.cbp.gov/travel/us-citizens/know-before-you-go/what-expect-when-you-return
- FDA Importing Cosmetics: https://www.fda.gov/industry/importing-fda-regulated-products/importing-cosmetics
- FDA MoCRA: https://www.fda.gov/cosmetics/cosmetics-laws-regulations/modernization-cosmetics-regulation-act-2022-mocra
- FDA Sunscreen: https://www.fda.gov/drugs/understanding-over-counter-medicines/sunscreen-how-help-protect-your-skin-sun
- FDA Cosmetic vs Drug: https://www.fda.gov/cosmetics/cosmetics-laws-regulations/it-cosmetic-drug-or-both-or-it-soap
- eBay Food Policy: https://www.ebay.com/help/policies/prohibited-restricted-items/food/-policy?id=4295
- eBay Browse API: https://developer.ebay.com/api-docs/buy/static/api-browse.html
- eBay Product Research/Terapeak: https://www.ebay.com/help/selling/selling-tools/terapeak-research-and-SEO?id=4853
- eBay Seller Fees: https://www.ebay.com/sellercenter/selling/start-selling-on-ebay/seller-fees
- Amazon Product Advertising API: https://webservices.amazon.com/paapi5/documentation/
- Keepa API Python client docs: https://keepaapi.readthedocs.io/
- Rakuten Ichiba Item Search API: https://webservice.rakuten.co.jp/index.php/documentation/ichiba-item-search
- Yahoo! Shopping API: https://developer.yahoo.co.jp/webapi/shopping/
- Reddit Developer Platform & Data API: https://support.reddithelp.com/hc/en-us/articles/14945211791892-Developer-Platform-Accessing-Reddit-Data
- Google Trends API Alpha: https://developers.google.com/search/apis/trends
- TikTok Research API: https://developers.tiktok.com/products/research-api/
- Nextdoor For Sale and Free Guidelines: https://help.nextdoor.com/s/article/Best-practices-For-Sale-Free?language=en_US
- Nextdoor Prohibited Goods and Services: https://help.nextdoor.com/s/article/List-of-prohibited-goods-and-services?language=en_US
- USPS Shipping Restrictions & HAZMAT: https://www.usps.com/ship/shipping-restrictions.htm
- USITC Harmonized Tariff Schedule: https://hts.usitc.gov/
