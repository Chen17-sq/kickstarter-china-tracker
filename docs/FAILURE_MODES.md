# Failure Mode Catalog · KS Tracker

每个可能让"错的东西被发出去"或"该发的没发"的故障面，按层归类。✅ = 已防 · 🟡 = 部分防 · ❌ = 未防 · 🆕 = 本次新增。

---

## A · 外部依赖故障

| # | 故障 | 状态 | 兜底机制 |
|---|---|---|---|
| A1 | Kickstarter Discover JSON 全 14 seed 被 CF 封 | 🆕 | discover 候选 <50 时 `scraper.run` 主动 abort，不会写空 projects.json |
| A2 | KS Discover JSON 字段静默改名（`pledged` → `pledge`） | 🆕 | sanity 检查 live 项目 backers >0 比例，全字段失踪会触发 |
| A3 | KS GraphQL `watchesCount` 字段改名 | ✅ | sanity gate followers 覆盖率 <30% 阻断 |
| A4 | KS GraphQL `rewards` 字段改名 | 🟡 | 不阻断（pledge_min 是可选字段），但日志可见 |
| A5 | KS 整站全封中国 IP | ✅ | GH Actions runner 在美国云上，不受影响 |
| A6 | Anthropic API 翻译挂 | ✅ | translate 模块 try/except，跳过用英文 blurb |
| A7 | Resend API 全挂 | ✅ | 每个收件人单独 try/except，逐个失败不连锁 |
| A8 | Resend 域名 unverify | ✅ | 单封 422 不影响其他收件人 |
| A9 | GitHub Pages 短暂 down | 🟡 | 数据照发，邮件里链接暂时打不开（用户重试即可） |
| A10 | Cloudflare DNS 失效 | ❌ | 没监控 |

## B · Pipeline 内部逻辑

| # | 故障 | 状态 |
|---|---|---|
| B1 | Discover 跑通但 classify 全部判否 → 0 个中国项目 | 🆕 sanity gate 阻断 |
| B2 | Translation API 返回乱码 / 错语种 | ❌ 未防 |
| B3 | Currency 换算错（×100 / ÷100 bug） | 🆕 检查 pledged_usd 离群值（>10亿 = 异常） |
| B4 | 同项目跨 seed 数据冲突 | ✅ first-seen 策略，按 pathname dedup |
| B5 | 项目状态字符串大小写不一致 | ✅ KS 后端字符串稳定 |
| B6 | deadline 在过去但 status=live | ✅ `timeline_text()` 用 `max(0, ...)` |

## C · 文件系统 / 数据

| # | 故障 | 状态 |
|---|---|---|
| C1 | `data/projects.json` 写入中途被打断 → 半截 JSON | 🆕 改用 atomic write（temp + rename） |
| C2 | `data/subscribers.json` 并发写冲突 | ✅ Worker 有 SHA 重试 3 次 |
| C3 | `data/history/` 目录无限膨胀 | ✅ cleanup 模块按保留期裁剪 |
| C4 | history 时间戳乱序 → diff 找错"昨天" | 🆕 sanity 校验 prev_snapshot 时间在 curr 之前 |
| C5 | 备份 history 文件本身坏掉 | ❌ 没校验 |

## D · 输出生成

| # | 故障 | 状态 |
|---|---|---|
| D1 | PDF Playwright 渲染崩 | 🆕 scrape.yml 加 `timeout-minutes: 20` 防止挂死 |
| D2 | Carousel 9 张少于预期 | ❌ 没检查 |
| D3 | banner.svg 含 git conflict 标记 | ✅ pre-commit hook 拦 |
| D4 | edition HTML 字体加载失败 | ❌ 不会自检 |

## E · 邮件内容

| # | 故障 | 状态 |
|---|---|---|
| E1 | 邮件 subject / body 含未转义控制字符 | ✅ 走 `_esc()` |
| E2 | 邮件含 HTML 注入（恶意 blurb_zh） | 🆕 全文复审 escape 链 |
| E3 | 邮件图片 hotlink KS CDN，KS 反爬 | 🟡 风险低，KS 静态图允许跨域 |
| E4 | 邮件链接走 ks.aldrich.fyi，DNS 当时挂 | ❌ 不会自检 |
| E5 | "Today" 时区错乱 | ✅ 全程 `datetime.now(UTC)` |

## F · 订阅者管理

| # | 故障 | 状态 |
|---|---|---|
| F1 | 订阅者邮箱失效 / 反复 bounce | ❌ 没 webhook，不知道 |
| F2 | 订阅表单被 bot 灌脏数据 | 🟡 CORS 白名单 + 邮箱格式校验，但无频率限制 |
| F3 | 订阅者想退订 | ❌ 没机制（只能 owner 改 NOTIFY_EMAIL_TO） |
| F4 | 同邮箱多次订阅 | ✅ Worker 大小写不敏感去重 |

## G · 调度

| # | 故障 | 状态 |
|---|---|---|
| G1 | GH Actions cron 跳过 | ✅ CC backup at 08:34 兜底 |
| G2 | CC backup 也跳过（Mac 关 / CC 关） | ❌ 没双备份 |
| G3 | scrape.yml 跑死循环 | 🆕 timeout-minutes: 20 |
| G4 | cron 连跳 7 天 → workflow 自动 disable | ❌ 没监控 |

## H · 安全

| # | 故障 | 状态 |
|---|---|---|
| H1 | Resend API key 被提交到 repo | 🟡 只在 env，但没 secret-scan |
| H2 | GITHUB_TOKEN 泄漏 | ✅ 只在 workflow env |
| H3 | Worker PAT 权限过宽 | ✅ scoped to single repo Contents |

## I · 可观测性 ⭐ 最大缺口

| # | 故障 | 状态 |
|---|---|---|
| I1 | 数据慢慢漂错，没人察觉 | 🆕 **每日 owner 摘要邮件**：跑成功也发给 owner 一封简报 |
| I2 | sanity 阻断了广播但 alert 也没到 | ❌ 单一 owner 邮箱，没备份接收人 |
| I3 | Pipeline 步骤静默失败（无 commit） | 🆕 `gh run` 失败时给 owner 发 alert |

---

## 本次实施优先级

**今天落地（5 项）：**
1. **C1** atomic write `projects.json`
2. **A1, B1, B3** sanity gate 加 schema/outlier 检查
3. **D1, G3** workflow timeout
4. **C4** history 时间戳合法性校验
5. **I1** owner 每日"成功也发"摘要邮件 — 你随时知道今天的状态

**下次再做（视情况）：**
- E2 邮件 escape 全文复审
- F1 Resend bounce webhook
- F3 退订链接
- G2 CC backup 双链路（如 Cloudflare cron 兜底）
- I2 备份 owner 邮箱
