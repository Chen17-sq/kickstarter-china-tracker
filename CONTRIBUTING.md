# 贡献指南

> 最有价值的 PR：**扩 `brands/china_brands.yaml`** 和 **改 `data/blurbs_zh.json`**。
> 每加一条品牌或一句中文，cron 第二天就把它带进当日报告。

---

## 补品牌白名单 → `brands/china_brands.yaml`

KS 上很多中国团队用美国地址注册，单看 KS location 字段会漏掉。手工录入品牌后，scraper 会按 creator_slug 命中。

**条目结构**：

```yaml
- {brand: "XGIMI",  brand_zh: "极米",  creator_slugs: ["xgimititannoir"],  hq: "成都",  source: "official-site"}
```

字段含义：

| 字段 | 是否必填 | 说明 |
| --- | :---: | --- |
| `brand` | 必填 | 品牌名（英文优先） |
| `brand_zh` | 可选 | 中文显示名（不填则前端 fallback 到 `brand`） |
| `creator_slugs` | 必填 | KS URL 第二段路径（一个品牌可有多个：账号迁移 / 多个产品线） |
| `hq` | 推荐 | 城市（深圳 / Hong Kong / 台北 / …） |
| `source` | 必填 | `official-site` / `direct-verification` / `news` 三选一 |

`source` 三档：

- **`official-site`** — 品牌自己的官网 about 页能确认中国背景（最可信）
- **`direct-verification`** — KS 项目页或 LinkedIn / Twitter 等有第一手痕迹
- **`news`** — 只有第三方报道（gizmochina / technode / 36kr / ifanr）— 适合刚露头的 prelaunch 项目

**找品牌信息的路子**：

- KS 项目页 About the creator → 邮箱域名 / 物理地址
- 品牌官网 About / Contact → 时区 / 邮箱 / 电话
- 微信 / 微博 / 抖音同名号
- 36kr / 创业邦 / 投资圈 中文报道
- ICP 备案查询（中国域名）

---

## 补中文一句话 → `data/blurbs_zh.json`

每一条用 8–28 个汉字描述**这个产品到底是什么**——不是分类标签（"智能硬件"），是产品定义（"4K 三色激光投影仪"）。

**风格示例**：

```
便携全自动浓缩咖啡机
1.7kg 全球最轻自行车助力套件（小米团队）
全球首款机械 + 磁轴混合可热插拔键盘
27 寸互动式光场裸眼 3D 显示器
```

**条目结构**：键是 KS 项目的 pathname（带前导 `/`），值是中文一句话：

```json
{
  "/projects/creator/project-slug": "中文一句话产品描述"
}
```

人工写的优先级 > LLM 自动生成的。如果觉得 LLM 写得不对劲，直接改 `blurbs_zh.json`，下次 cron 不会覆盖。

---

## 修分类错（"这个不是中国背景"）

- 把品牌移到 `not_china:` 段，标 `hq` 实际所在地
- 加个 `reason` 字段简短说明依据

---

## 改代码

```bash
pip install -r requirements.txt

# 跑某一个项目页 debug：
python -m scraper.project ayaneo-pocket-play-mobile-phone-and-gaming-handheld-in-one

# 端到端：
python -m scraper.run

# 邮件预览（不发）：
python -m scraper.email_notify --dry-run

# Slack/Discord 预览：
python -m scraper.notify --dry-run
```

---

## 报 bug

用仓库的 issue 模板（**[bug] 标题** + 现象 + 在哪看到的 + 那次 cron 的 commit hash），不需要写很长。
