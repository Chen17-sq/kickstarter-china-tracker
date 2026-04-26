# 部署订阅 Worker · 10 分钟

订阅页 (`subscribe.html`) 的提交按钮要把邮箱直接写到 `data/subscribers.json`，
但浏览器表单不能直接 commit 到 git。中间需要一个 serverless function 接住
表单 POST，调 GitHub API 把数据追加到仓库。

我们用 **Cloudflare Workers**，永久免费，10 分钟跑通。代码已经在仓库
`subscribe-worker/worker.js`，你只需要部署它 + 配两个 secret。

---

## Step 1 · 注册 Cloudflare（免费，2 分钟）

1. 打开 https://dash.cloudflare.com/sign-up
2. 用 schen.aldrich@gmail.com 注册（不需要绑卡，Workers 免费 100K req/day）
3. 验证邮箱，进 dashboard

---

## Step 2 · 创建 GitHub Personal Access Token（3 分钟）

Worker 要往仓库写文件，需要一个 GitHub token：

1. 打开 https://github.com/settings/tokens?type=beta
2. **Generate new token** → "Fine-grained personal access tokens"
3. 设置：
   - **Token name**: `ks-tracker-subscribe-worker`
   - **Expiration**: 1 year（到期前会邮件提醒）
   - **Repository access**: Only select repositories → 选 `kickstarter-china-tracker`
   - **Permissions** → **Repository permissions** → 找到 `Contents` → 设为 **Read and write**
4. 点 **Generate token** → 复制以 `github_pat_...` 开头的字符串（**只显示一次**）

---

## Step 3 · 部署 Worker（5 分钟）

最简单的方式 — 用 Cloudflare dashboard 网页操作（不用装命令行工具）：

1. 在 Cloudflare dashboard 左侧栏：**Workers & Pages** → **Create** → **Workers** → **Hello World** template
2. 起名 `ks-tracker-subscribe`（这会决定你的 URL：`https://ks-tracker-subscribe.<你的子域>.workers.dev`）
3. **Deploy** → **Edit code**
4. 删掉默认的 hello world 代码，**完整复制**这个仓库 [`subscribe-worker/worker.js`](../subscribe-worker/worker.js) 的所有内容粘进去
5. 右上角 **Save and deploy**

---

## Step 4 · 配置 Worker 变量（2 分钟）

回到 Worker 详情页 → **Settings** → **Variables and Secrets**：

**Add variable**（普通环境变量，未加密）：
- Name: `GITHUB_REPO` · Value: `Chen17-sq/kickstarter-china-tracker`
- Name: `ALLOWED_ORIGIN` · Value: `https://chen17-sq.github.io`

**Add variable** → 选 **Encrypt**（敏感，加密存储）：
- Name: `GITHUB_TOKEN` · Value: 粘贴 Step 2 拿到的 `github_pat_...`

**Save and deploy**

---

## Step 5 · 把 Worker URL 填到订阅页（1 分钟）

1. 回到 Worker 顶部，复制它的 URL（形如 `https://ks-tracker-subscribe.<your-subdomain>.workers.dev`）
2. 把 URL 给我，我帮你换进 `subscribe.html` 的 form action（或者你自己改一下：把 `REPLACE_WITH_FORMSPREE_ID` 那一段替换成你的 Worker URL）
3. Commit + push

---

## 测试

打开 https://chen17-sq.github.io/kickstarter-china-tracker/subscribe.html，
填一个测试邮箱（比如你的备用邮箱），点订阅。

**正常情况**：
- 浏览器立刻显示"订阅成功"
- 几秒后 GitHub 仓库出现一个新 commit `+sub j***@gmail.com via worker`
- `data/subscribers.json` 里多了一条记录

**翻车排查**：
- Worker logs：Cloudflare dashboard → 你的 Worker → **Logs** 看实时报错
- 常见错误：
  - `HTTP 401` → GitHub token 没权限或过期
  - `HTTP 404 contents/data/subscribers.json` → GITHUB_REPO 写错了
  - `CORS error` → ALLOWED_ORIGIN 跟 Pages URL 不一致

---

## 费用

- Workers: 100,000 req/day 免费 — 一辈子用不完
- GitHub Contents API: 5,000 req/hr 免费 — 同理
- 总成本：**$0/月**

---

## 改/删订阅者

直接编辑 `data/subscribers.json` commit。或者：

```bash
python -m scraper.subscribers remove someone@example.com
git commit -am "-sub someone@example.com"
git push
```

不需要走 Worker。
