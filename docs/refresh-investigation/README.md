# 数据刷新事故排查与修复（2026-10-07）

当前状态：本地修复及离线回归已完成，线上采集仍待受控验证。未部署、未改生产数据、未删除历史、未发送或重发邮件。质量拦截策略默认 **observe**，生产是否启用 `KS_QUALITY_POLICY=enforce` 由仓库所有者确认。

## 证据与结论

检查基线：`950be97e6ae45677e9acc390cd8fe8dd400e6419`。主要一手证据：

- [10 月 7 日 scrape 运行](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37565957013)：discover 765 candidates；watches `0/248`；minimum pledge `0/248`；恢复 218 followers；catalog refresh `0/980`；补回 739 yesterday-known projects；邮件 `sent=9, failed=0`。
- [10 月 6 日运行](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37410703561)：watches `0/256`，minimum pledge `0/256`，恢复 233，catalog `0/969`，邮件 9 封。当天分母实际为 256，不能沿用 10 月 7 日的 248。
- [9 月 27 日运行](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/36288605747)：watches `0/235`，minimum pledge `0/235`，恢复 233，catalog `0/921`，邮件 9 封。
- [10 月 1 日运行](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/36808715005)：watches `247/247`，minimum pledge `158/247`，catalog 只有 `45/943`。各来源、各字段的状态显著不同。

### 1. 入口失败与程序恢复缺陷叠加

10 月 7 日日志连续记录：curl seed HTTP 403；Playwright `CSRF token not found after Playwright navigation`；nodriver `Failed to connect to browser`。这是可确认的入口／回退故障，不支持“只是限流”或“所有解析器失效”的推断。没有发现 429 是这些失败的必要解释。

只读浏览器核验：Discover 页 HTTP 200 且 CSRF meta 存在，页面自身 GraphQL 请求同时出现 200/403；单次公开项目 GraphQL 查询返回 403 HTML，标题 `Just a moment…`。故不能认定字段已被移除，不能声称线上刷新已经恢复。未绕过挑战或登录。

代码中还存在可确定的故障：

- 共享 transport 打开失败返回 `None`，下游又把 `None` 当作“请重新打开”，watches、pledge、catalog 各自再走完整回退链。修复为区分“参数未传入”和“已知打开失败”。三条路径复用同一 transport。
- nodriver 在 boot、每次 query、close 分别执行 `asyncio.run()`，每次关闭其事件循环；已有 websocket/后台任务无法可靠跨调用存活。改为单一拥有完整生命周期的事件循环，并测试后台任务清理。CI 显式使用已安装的 Chromium 路径，避免依赖浏览器自动搜索。它是已证实的代码缺陷，但现有日志不能证明它单独解释了全部浏览器启动失败。
- 原 refresh 补充仅处理 discover 未出现的 pathname；已在 discover 的项目即使 GraphQL 刷新成功，也会被跳过。改为逐字段合并，保留成功来源。
- HTTP 200 的空对象／GraphQL errors、缺失金额和非 USD 金额不能当作数值成功；原 `_num(None) -> 0`、盲信 currency cookie 的逻辑已修。

### 2. 旧数据被赋予当日身份

旧代码明确写着旧 followers 恢复后“Δ = 0”，但这没有新观测支持。旧目录原样补入新 snapshot，只有全局 `generated_at`，无字段观测时间；浅拷贝还携带上一轮 `delta_*`／`weekly_delta_*`。发送门槛按有无正数判断覆盖，旧值可轻易通过；followers 85% 以上不变只给出 `broadcasting anyway` 提示。

修复后的每个动态字段具有 `observations`：`status`、`attempt_status`、`observed_at`、`attempted_at`、`source`、`unit`、`basis`、失败原因。沿用旧值保留原 `observed_at`；旧格式没有观测时间时记为 unknown/null，绝不从文件时间补造。快照仍保留完整目录及失败尝试，但它们不会变成新的有效观测或增量基线。

### 3. 窗口、口径和币种

- 日增量只接受相隔 24±6 小时的观测；周增量接受 7 天±12 小时。窗口超出、币种／转换口径不一致、缺失或旧格式无证据，返回 JSON `null` 和原因，显示“无法计算”。
- 同日恢复从昨日附近基线计算，不把刚才失败的一次当成“24h”。同一秒重跑也追加独立 attempt 文件。
- 实际零增长保留 0；金额缺失不会填 0。GraphQL 原生非 USD 金额单独记录，只有与已知原币种匹配的可靠静态汇率才转换；否则 USD 字段保留旧时间并标陈旧。
- 日报和网站共用同一 `observations` / `delta_meta` 契约；API 升至 schema v2；周报净增改为同一项目集合的可比、有正有负的增量。覆盖不完整时不冒充完整总增长。

原“7 天零变化”告警还存在文件序号错误：10 月 7 日写完今日文件后取倒数第 7 份，实际取到 **10 月 1 日 03:12:56Z**，约 6 天。按原 `live、金额≥$100、差额<$1` 条件可精确复现 **469**。真正的周增量基线为 9 月 30 日；同样条件计 459，单纯 `weekly_delta_pledged_usd == 0` 则为 487。三个数字口径不同，不能互换。已改按时间选取且要求有效观测。

## 历史影响范围

审计文件：[`historical-refresh-audit.csv`](historical-refresh-audit.csv)、[`historical-refresh-summary.json`](historical-refresh-summary.json)。

- HEAD 保留 **82 份**历史快照，日期范围 **2026-07-09～2026-10-07**；全部没有字段级观测证据。79 个快照日仍有非零筹款日增量，不能整体置零或宣告全部来源失效。
- 读取 9 月 1 日～10 月 7 日 37 次每日运行日志；35 次产生快照并发出 9 封邮件，9 月 3 日和 9 月 28 日运行达到约 20 分钟超时被取消，不能当成成功日报。
- 35 次正常结束的运行中，catalog refresh 均不完整，只有 0～46 条／782～980 条；这些日期均建议标为“目录更新不完整，增长仅限有证据项目”。其中 **16 天 catalog 为 0**，逐日列于 JSON/CSV。
- **14 天 watches 为 0**：9/12、9/17、9/18、9/19、9/21、9/27、9/29、9/30、10/2、10/3、10/4、10/5、10/6、10/7。9/11 为 100/264，也属部分失败。10/4 的最低档位却为 153/249，再次说明不同字段不能合并判断。
- 10/7 快照：987 项，597 live；980 项 followers 与上份相同；905 项筹款日增量为 0，**75 项非零**，7 个新项目无日增量。不能把 905 个零直接解释成真实零增长。
- 仓库有 153 份历史 Markdown 日报；代码缺陷分别至少可追溯到 4/28 的旧值恢复、5/16 的周增量、5/24 的目录补回。7/9 以前本次未逐日恢复已被保留策略移除的快照，属于待进一步审计范围，不宣称这些日期全部失效。

建议处理（尚未执行）：保留原始日报／快照及邮件记录；添加单独的逐日报表质量标注或勘误索引；先覆盖上述 35 个不完整运行日和 14 个 watches 全失败日；有原始成功响应且时间、口径可验证时才生成新版本修订数据。仅能确认“旧值沿用”的字段标未知／无法计算，不用插值或当前值重建过去。历史邮件是否发勘误由所有者另行决定。

## 发送前质量门槛建议（待确认）

代码已输出建议门槛结果，但默认观察，不自动执行新拦截政策：

| 检查 | 建议阈值 | 依据 |
|---|---|---|
| 核心新鲜覆盖 | prelaunch followers、live backers、live pledged 各≥90% | 防止目录中大部分旧值掩盖可用小样本；分状态取分母 |
| 新鲜度 | 成功观测距发布≤30h | 适应日 cron 漂移，仍明确限制继承旧值 |
| 增量覆盖 | 核心字段可比日基线≥80% | 部分新项目可无基线，但不能用少数更新项目代表全目录 |
| 异常零变化 | 可比样本≥20且≥95%为零，进入人工复核 | 作为异常信号，不能反推所有单项零都是抓取失败 |
| 最低支持档位 | 独立展示覆盖率、币种和缺失，不作核心筹款门槛 | prelaunch 可尚无奖励，档位不是筹款总额 |

阈值是针对日频产品的初始工程建议，尚未以完整历史有效观测分布校准。开启 enforcement 后，异常零变化也会阻止普通增长报告，需要人工复核。可选择继续观察、低质量只发故障摘要、或阻止普通报告；当前提交没有替用户作生产选择。既有空目录、重复 pathname、异常金额等结构性保护仍保留。

`data_quality` 记录数据刷新，`.delivery_health.json` 和发送日志记录邮件 sent/failed，两者独立。恢复流程不再删除历史，`refresh_only=true` 明确跳过邮件；同日有历史尝试也不会自动再发。生产部署需先确认策略，并核对数据与发信状态。

## 修改文件

- `scraper/observations.py`、`quality.py`：观测契约、可比判断、新鲜度、覆盖与异常零变化。
- `scraper/run.py`、`refresh.py`、`project.py`、`discover.py`、`nodriver_transport.py`：采集失败语义、共享连接、逐字段合并、原观测时间、解析和币种检查、循环生命周期。
- `scraper/momentum.py`、`diff.py`、`anomalies.py`、`weekly.py`：日／周基线、真零与不可算、历史文件不等于天数、避免旧增量进入新闻／榜单。
- `scraper/email_notify.py`、`notify.py`、`report.py`、`api.py`、`health.py`、`sanity.py`、`banner.py`、`social.py`：统一展示、独立刷新／送达状态及观察模式门槛；README图卡与社交导出同样标记未更新。
- `site/app.js`、`index.html`、`stats.html`：状态、观测时间、旧值参考和移动预览。
- `.github/workflows/{scrape,scrape-retry,test}.yml`：刷新与发信分离、不删历史、指定 Chromium、测试依赖。
- `scripts/emergency_refresh.py`：复用主链路，避免第二套无证据计算。
- `scripts/dry_run.py`、`audit_refresh_history.py`、`scraper/tests/test_refresh_integrity.py` 及原有相关测试：隔离回放、历史审计、回归。

## 测试和修复前后样例

测试环境 Python 3.12，venv 位于仓库 `.venv`。执行：

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check scraper scripts/dry_run.py scripts/audit_refresh_history.py
.venv/bin/python -m compileall -q scraper
# 每个 --output 必须是仓库外尚不存在的新目录；网络和发信均强制禁用。
.venv/bin/python scripts/dry_run.py --scenario all-failed --output /tmp/ks-all-failed-new
.venv/bin/python scripts/dry_run.py --scenario partial --output /tmp/ks-partial-new
.venv/bin/python scripts/dry_run.py --scenario healthy --output /tmp/ks-healthy-new
.venv/bin/python scripts/dry_run.py --scenario recovery --output /tmp/ks-recovery-new
.venv/bin/python scripts/audit_refresh_history.py --logs /tmp/ks-refresh-evidence --output /tmp/ks-audit-new
```

回归覆盖：全部失败、单字段／部分项目失败、HTTP 200 空 data、GraphQL 错误、旧值恢复、未知旧时间、缺基线、真实零、非零／负增长、币种口径变化、时间窗口错误、恢复重跑、同秒保留尝试、单事件循环、观察与拦截策略、结构性保护、无网络／无发信约束。原测试改用有明确观测证据的 fixture，另有专门测试保证 legacy 不被默认为有效。

| 隔离场景 | 项目数 | 有效日筹款增量 | 留存历史数 | 网络请求／邮件 |
|---|---:|---:|---:|---:|
| 全部失败 | 30 | 0 | 3 | 0 / 0 |
| 部分失败 | 30 | 24 | 3 | 0 / 0 |
| 全部来源成功、1项无基线 | 30 | 29 | 3 | 0 / 0 |
| 失败后同日恢复重跑 | 30 | 29 | 4 | 0 / 0 |

| 样例 | 修复前 | 修复后 |
|---|---|---|
| 旧值 100，今日抓取失败 | 今日仍100，差额0 | 未更新；旧值100，原始时间保留；差额无法计算 |
| 基线金额缺失，今日1052 | `1052 - 0 = +1052` | 当前1052；差额null／无法计算 |
| 两次有效观测1000→1000 | 0与失败混淆／隐藏 | 明确 `$0`，有可比窗口证据 |
| 有效筹款1000→1051，关注失败 | 全部字段可能一起降级／旧关注显示0 | 筹款 `+$51`；关注未更新、关注差额无法计算 |
| HKD 50000，旧USD1000且无可靠换算 | 旧USD冒充当日／奖励币种误标USD | 原生HKD独立记录；USD未更新，不计算USD增长 |

网站和邮件专项预览使用 Fixture 00/01/02/21 对应真零、非零与部分失败、缺基线、全旧值；普通Top10另行验证。浏览器检查和最终测试结果见本目录验证记录。

## 尚未验证

- GitHub 托管 runner 的真实采集成功率、当前 Kickstarter 挑战能否解除；没有运行生产采集 workflow，也没有变更会话、代理或生产凭据。
- nodriver 使用安装路径后在 GitHub runner 的真实启动；本次验证了 API（nodriver 0.50.5）及生命周期回归，不能替代线上 smoke test。
- 新字段上线前的历史基线缺失将使初期日／周增量不可算；至少需要两次时间窗口合适的成功观测。不会为让首日报表好看而接受旧格式假基线。
- 真实邮件服务和收件客户端渲染未发信测试；本地 HTML 浏览器预览不等于 Gmail/Outlook 全客户端认证。
