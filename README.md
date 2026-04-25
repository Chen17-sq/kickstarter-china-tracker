# Kickstarter China Tracker

实时追踪 **Kickstarter 上中国背景的消费硬件项目**——重点是 *prelaunch*（含 follower 数）和 *live*（含 backers / 已筹金额 / 完成率）两个阶段。

数据每 4 小时自动刷新一次，跑在 GitHub Actions 上。前端是个静态 HTML，挂在 GitHub Pages 上零成本运行。

## ✨ Features

- 🔄 **每 4 小时**自动抓取 KS Discover 列表 + 每个候选项目页
- 🇨🇳 三层规则识别中国背景：品牌白名单 + KS location 字段 + 启发规则
- 📊 历史快照沉淀在 `data/history/` —— 可画 follower 增长曲线
- 🔔 Slack / Discord webhook 推送大变动（新项目、follower +500、backers +100）
- 🌐 GitHub Pages 静态前端，零服务器
- 📥 项目数据全部以 JSON 暴露，可被任意第三方仪表盘消费

## 🚀 Quick start

```bash
git clone https://github.com/YOUR_HANDLE/kickstarter-china-tracker.git
cd kickstarter-china-tracker
pip install -r requirements.txt
python -m scraper.run        # 本地跑一次完整 pipeline
open data/projects.json
```

把 fork 推到自己的 GitHub 后：
1. **Settings → Actions → General**：勾上 "Read and write permissions"
2. **Settings → Pages**：Source 选 GitHub Actions
3. （可选）**Settings → Secrets**：加 `SLACK_WEBHOOK` / `DISCORD_WEBHOOK`
4. 在 Actions 页手动跑一次 *scrape* workflow → 接着 *deploy-pages* 自动跑 → 你的 Pages 站就有数据了

## 🗂 Repo layout

```
kickstarter-china-tracker/
├─ scraper/            # 抓取 + 分类 + 比对
│  ├─ http.py            polite httpx + USD currency cookie
│  ├─ discover.py        遍历 China / Tech / Design 的 Discover seeds
│  ├─ project.py         单项目页解析（followers/backers/$$$/PWL/days）
│  ├─ classify.py        三层规则判断中国背景
│  ├─ diff.py            两次快照间的变化，输出 CHANGELOG.md
│  ├─ run.py             pipeline 入口（GitHub Actions 调用）
│  └─ notify.py          Slack/Discord webhook
├─ brands/
│  └─ china_brands.yaml  品牌白名单（可 PR 维护）
├─ data/
│  ├─ projects.json      最新快照（前端读这个）
│  ├─ prelaunch.json     仅 prelaunch
│  ├─ live.json          仅 live
│  ├─ projects-seed.json 项目首版手工种子（97 条）
│  └─ history/           每次 cron 一份时间戳快照
├─ site/                 GitHub Pages 静态站
├─ .github/workflows/
│  ├─ scrape.yml         cron + commit
│  └─ deploy.yml         build + deploy pages
└─ README.md / ARCHITECTURE.md / CONTRIBUTING.md
```

## 🤖 自动化机制

```
                        ┌─────────────────────────────┐
                        │  cron: every 4 h (UTC)      │
                        └────────────┬────────────────┘
                                     │
                                     ▼
   ┌──────────┐   crawl_discover()   ┌──────────────────────┐
   │ Discover │ ──────────────────►  │  ~250 candidate URLs │
   │  seeds   │                      └────────────┬─────────┘
   └──────────┘                                   │ 1 req/sec
                                                  ▼
                                ┌────────────────────────────┐
                                │ fetch_project() x N        │
                                │ → ProjectSnapshot dataclass│
                                └────────────┬───────────────┘
                                             │
                                             ▼
                                ┌────────────────────────────┐
                                │ classify(): brand whitelist│
                                │ + location + heuristics    │
                                └────────────┬───────────────┘
                                             │ keep 高 / 中
                                             ▼
                            ┌──────────────────────────────────┐
                            │ data/projects.json               │
                            │ data/history/<ts>.json           │
                            │ CHANGELOG.md (vs previous run)   │
                            └────────────┬─────────────────────┘
                                         │
                ┌────────────────────────┼────────────────────────┐
                ▼                        ▼                        ▼
       git commit + push       deploy GH Pages        Slack/Discord webhook
```

## ❤️ 礼貌爬取

- `User-Agent` 标明项目身份和 repo 地址
- 限速 ≤ 1 req/sec
- HTTPS 直连 KS 站点（不绕代理、不抓登录态接口）
- 不订阅、不通过项目页面以外的接口拉非公开数据
- 全部数据来自 KS 公开 Discover/项目页 HTML
- 完整流程每 4 小时一次（共 ~250 次请求 / 几分钟），对 KS 几乎零负担

## 📝 License

MIT. See `LICENSE`.

## 🙏 Credits

- 项目种子（97 条）由 Cowork 模式下的人工 + Claude in Chrome 实测整理（2026-04-25 快照）
- 灵感来自 PrelaunchClub、PledgeBox、Kicktraq 等社区的众筹观察文化
