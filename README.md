![Kickstarter China Tracker — daily editorial briefing](assets/banner.svg)

**[→ 在线看板 chen17-sq.github.io/kickstarter-china-tracker](https://chen17-sq.github.io/kickstarter-china-tracker/)** · **[今日报告](reports/latest.md)** · **[原始 JSON](data/projects.json)**

> 实时追踪 **Kickstarter 上中国背景的消费硬件项目** —— 覆盖 *prelaunch* / *live* / *已结束* 三个阶段。
> Live data refreshed daily at 01:00 UTC (09:00 Beijing).

---

## 它是什么

每天一次，cron 通过 KS Discover 的内部 JSON API 抓全站的中国地区 + 全球 Tech / Design 三个 seed 列表，按"中国背景"规则筛出 ~140 个项目，分类为 prelaunch / live / 已结束。每个项目带：

- 公司 / 创作者（中英双语，有中文名的优先显示中文）
- 产品一句话介绍（手工 + LLM 自动翻译）
- 实时已筹金额、Backers、完成率、★ KS 精选标签
- 国家、城市、品类
- 直达 KS 项目页的链接

数据通过 GitHub Pages 的静态前端展示（Editorial / Swiss 设计），同时落到 [`data/projects.json`](data/projects.json)，并生成一份 [`reports/YYYY-MM-DD.md`](reports/) 的 Markdown 日报追踪状态变化。

---

## 当前规模

| 抓取节奏 | 覆盖 seed | 中国背景项目 | 中文一句话覆盖 | KS 精选 |
| ---: | ---: | ---: | ---: | ---: |
| 每日 1 次 | 8 个 Discover 列表 | ~138 个 | 100 / 138（人工 + LLM 自动） | ~30 |

> 每次 cron 跑完会 commit 一份 `data/history/<时间戳>.json` 快照，长期沉淀做时间序列分析。

---

## 怎么工作的

1. **`scraper/discover.py`** — 用 `curl_cffi` 模拟 Chrome / Safari TLS 指纹绕过 Cloudflare，访问 `kickstarter.com/discover/advanced?...&format=json`。该端点是 KS 自己 Discover 页客户端分页用的，返回完整的项目对象（包含 pledged / backers / staff_pick / location 等所有字段）。
2. **`scraper/classify.py`** — 三层规则判定中国背景：（a）`brands/china_brands.yaml` 品牌白名单命中（覆盖在美国注册 KS 账号但实际中国团队的品牌）；（b）KS location 字段在 China / Hong Kong / Taiwan / Macau；（c）人工标注的 medium-confidence。
3. **`scraper/translate.py`** — 对没有人工中文一句话的项目，调用 Claude Haiku 4.5 自动生成。结果写回 `data/blurbs_zh.json`，下次 cron 不再重复翻译。需要 `ANTHROPIC_API_KEY` secret，没设置就跳过。
4. **`scraper/report.py`** — 对比当前快照和上一份历史快照，生成一份 Markdown 日报：今日新增、状态变化、Top prelaunch、Top live、最近成功。
5. **`scraper/run.py`** — 串起以上四步 + 一道安全闸（如果分类结果 < 20 项，拒绝覆盖 `projects.json`，避免 Cloudflare 偶尔挡爬时清空数据）。
6. **`.github/workflows/scrape.yml`** — cron `0 1 * * *` 每天触发；commit `data/`、`reports/`、`CHANGELOG.md`。
7. **`site/`** — vanilla HTML + JS + CSS 静态前端，Inter / Inter Tight 字体，挂在 GitHub Pages 上。带中英 toggle、按状态/置信度/PWL 筛选、按已筹/Backers/完成率排序。

---

## 仓库结构

```
.
├── data/
│   ├── projects.json        当前快照（前端读这个）
│   ├── prelaunch.json       仅 prelaunch
│   ├── live.json            仅 live
│   ├── blurbs_zh.json       中文一句话产品描述（人工 + LLM）
│   ├── projects-seed.json   97 条手工种子（首次 bootstrap）
│   └── history/             每次 cron 一份时间戳快照
├── brands/
│   └── china_brands.yaml    品牌白名单（PR 友好）
├── reports/
│   └── YYYY-MM-DD.md        每日 Markdown 报告
├── scraper/
│   ├── http.py              curl_cffi + TLS 指纹轮换
│   ├── discover.py          KS Discover JSON 抓取
│   ├── classify.py          三层规则判定
│   ├── translate.py         Claude Haiku 自动翻译
│   ├── report.py            日报生成
│   ├── run.py               主 pipeline
│   ├── diff.py              snapshot diff
│   └── notify.py            可选 Slack/Discord webhook
├── site/                    GitHub Pages 静态站
│   ├── index.html
│   └── app.js
├── .github/workflows/
│   ├── scrape.yml           每日 cron
│   └── deploy.yml           Pages 自动部署
├── ARCHITECTURE.md
└── CONTRIBUTING.md
```

---

## 本地跑一次

```bash
git clone https://github.com/Chen17-sq/kickstarter-china-tracker.git
cd kickstarter-china-tracker
pip install -r requirements.txt

# 抓取 + 分类 + （可选）翻译 + 报告
python -m scraper.run

# 看输出
cat data/projects.json | jq '.kept'
ls reports/
```

启用自动翻译（可选）：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m scraper.run
# 现在没有中文一句话的项目会被 Claude Haiku 自动翻译
```

跑前端站：

```bash
python -m http.server 8000 -d site
# 浏览器打开 http://localhost:8000
```

---

## 部署到自己的 GitHub

Fork 这个仓库后：

1. **Settings → Actions → General**：勾上 *Read and write permissions*
2. **Settings → Pages**：Source 选 *GitHub Actions*
3. **Settings → Secrets**（可选，强烈推荐）：
   - `ANTHROPIC_API_KEY` — 启用自动中文翻译
   - `SLACK_WEBHOOK` 或 `DISCORD_WEBHOOK` — 启用大变动推送
4. Actions 标签页手动触发一次 *scrape* → Pages 自动跟进 → 你自己的 tracker 站就活了

---

## 贡献

最有价值的 PR：

- **扩 `brands/china_brands.yaml`**：每加一个品牌白名单条目，就能多覆盖一批用美国地址注册 KS 但实际中国团队的项目。条目结构：`{ brand: "极米", brand_zh: "极米", creator_slugs: ["xgimi-projector"], hq: "成都", source: "official-site" }`。
- **改 `data/blurbs_zh.json`**：人工写的中文一句话比 LLM 自动翻译质量更高。已有 100 条人工译文，可以补也可以改。
- **加 `medium_confidence` 条目**：发现疑似中国背景但没确认的项目，先放 medium 列表标 reason，后续人工复核。

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 已知限制

- **Cloudflare 概率挡爬**：`scraper/http.py` 已经做了 4 次 retry + TLS 指纹轮换（Safari 17 / Chrome 131 / Chrome 120 / Edge 101），命中率 > 95%。极少数情况下整次 cron 会被全挡，安全闸会拒绝覆盖 `projects.json`，下一次 cron 自然恢复。
- **品牌库覆盖率**：当前 138 项目里 34 项命中品牌白名单，104 项靠 KS location 字段判定。前者识别更精确，后者会捕获到一些"在中国设了工作室的非中国创始人"项目。
- **Followers 字段语义**：当前从 KS GraphQL 的 `watchesCount` 字段读取。对 *prelaunch* 项目这是当前实时关注数；对 *live* / *已结束* 项目这是上线时冻结的预热基线（仍然有用——可以看转化率），但不是项目生命周期内的实时关注变化。

---

## License

MIT — see [LICENSE](LICENSE). 数据归 Kickstarter 所有，本仓库只做聚合 + 展示，不做转售。
