# 全面修复最终验收 · 2026-10-07

代码已更新GitHub并投入生产采集。最终快照为 **2026-10-07T12:31:31Z（北京时间20:31:31）**，共970个独立项目、21个保留别名。采集恢复与可比增长分开判断：核心数据新鲜覆盖已超过96%，日/周增量仍因缺少可靠时间窗口基线而明确显示无法计算；邮件保持暂停。

## 生产证据

- 核心采集/观测契约：[PR #7](https://github.com/Chen17-sq/kickstarter-china-tracker/pull/7)；不可变归档：[PR #8](https://github.com/Chen17-sq/kickstarter-china-tracker/pull/8)。
- 汇率、奖励分页、展示与勘误：[PR #9](https://github.com/Chen17-sq/kickstarter-china-tracker/pull/9)；官方状态补齐：[PR #10](https://github.com/Chen17-sq/kickstarter-china-tracker/pull/10)；稳定项目ID排重：[PR #11](https://github.com/Chen17-sq/kickstarter-china-tracker/pull/11)。
- 最终代码`3002ef1`，生产快照提交`37d46d8`，[不发信真实刷新](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37620201034)。
- 真实刷新结论success；Email与Slack/Discord步骤均skipped。[最终Pages部署](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37621894255)成功。
- [最终五项CI](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37619896826)全部通过。只读source探针绿色仅说明完成诊断，真正恢复依据是上述生产响应及观测证据。
- 机器可读逐项验收：[final-acceptance.json](final-acceptance.json)。

最终目录49个批次请求970个不同slug、返回961个对象，均记录为结构化response；对应982/991个旧路径字段刷新成功。watch字段得到430/439，最低档位数值213/439（该范围还包含无奖励的预热及Discover记录，不能与live档位分母143混用）。独立项目覆盖以如下字段级表格为准。

| 指标 | 最终结果 |
|---|---:|
| 独立项目 / 保留别名 | 970 / 21 |
| 具有官方项目ID证据 | 961，重复ID为0 |
| 预热关注新鲜覆盖 | 217/225，96.4% |
| 在筹支持人数新鲜覆盖 | 142/143，99.3% |
| 在筹USD筹款新鲜覆盖 | 142/143，99.3% |
| 在筹最低档位新鲜覆盖 | 142/143，99.3% |
| active状态未确认 | 9/368，继续计入分母 |
| 既有归档完整性 | 660文件逐项SHA256一致，无删除/改写 |
| 旧项目路径保留 | 全部保留，缺失路径0 |
| 原币×平台汇率一致性 | 错误0 |

本次分母按官方项目身份排重；此前151个live路径还包括7个别名，并有1个项目在运行间正常结束，最终为143个独立live项目。预热228个路径中有3个别名，最终225。数量下降有身份与状态证据，不是把失败项目排除分母。

LightMake L4两条路径经官方`pid=206217094`确证同一项目，主路径`/projects/lightmake/lightmake-l4-1st-4-head-color-3d-printer-with-linear-motor`保留数字creator路径为alias。其本次身份观测时间为12:28:15Z；同标题或相同金额本身从未作为合并条件。

## 根因与受影响范围

1. 日志查实入口403、CSRF缺失及浏览器启动失败；代码还存在共享transport失败被重复开启、nodriver跨事件循环与实际序列化协议处理错误。不能据此断言全部是限流或所有数据源失效。
2. 9/1–10/7的35次完成运行，目录刷新均不完整；19次有返回的运行成功对象数恰等于总数对50取余。20项目录批次及逐批错误诊断已恢复正常。旧日志丢弃服务端错误，因此具体复杂度阈值仍不作已证实结论。
3. 旧值恢复被视作新观测、旧delta被复制、缺失金额被转成零；周比较还把倒数第7个文件当7天。旧469个零变化可按原算法复现，但不能解释为469个真实零增长。
4. 金额币种和转换证据不足、最低奖励缺完整分页、状态长期未刷新、同项目别名重复，分别造成金额缺口、价格不可靠、过期live与重复排名。

详细日志、历史范围和修改文件见[排查报告](README.md)、[批次与浏览器证据](CONTINUED-REPAIR.md)、[汇率/状态/身份补齐](COMPLETION.md)。

历史审计覆盖82份原快照（7/9–10/7）及9/1–10/7的35次完成运行，其中14天watches全失败；并非所有日期所有字段失效。153份4/25–10/7原日报新增[逐日勘误](https://ks.aldrich.fyi/corrections.html)：有日志日期标采集不完整，其余标观测证据不足。保留原刊、快照及版本，不插值、不用当前值回填历史、不自动补发勘误邮件。

## 修复前后样例

| 情况 | 原问题 | 修复后 |
|---|---|---|
| 抓取失败沿用旧值 | 写入当天并得到0增长 | 保留原observed_at；未更新／无法计算 |
| 无可靠昨日基线 | 缺失被当成0 | JSON null，附不可比原因 |
| 真实零增长 | 与失败混淆 | 新旧有效可比观测确实相等时显示0 |
| 汇率变化 | USD账面变化混入筹款增长 | 原币增量按当前明确USD汇率折算；样例1000→1093.04的可比增长为53.04 |
| 价格小于1美元 | 四舍五入成0 | 例如0.13保留两位小数；完整空奖励列表显示暂无档位 |
| STARTED | 新关注已返回，状态仍待确认 | 明确映射prelaunch并记录当前raw_state，18项恢复 |
| 同项目两路径 | 两个排名、重复统计 | 仅凭官方相同ID合并计数，保留alias与旧历史 |

第一轮真实恢复时USD筹款仅85/151、最低档位10/151；补齐平台USD汇率与奖励分页后达到150/151，再经状态变更和身份排重得到当前142/143。不同阶段分母变化已逐项解释。

## 回归与复现

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check scraper scripts/currency_probe.py scripts/build_corrections.py
node --check site/app.js
git diff --check

replay_root=$(mktemp -d /tmp/ks-replay.XXXXXX)
for scenario in all-failed partial healthy recovery currency aliases; do
  .venv/bin/python scripts/dry_run.py --scenario "$scenario" --output "$replay_root/$scenario"
done
```

结果：**330 passed**；Ruff、JS语法与diff检查通过。六种隔离全链路回放均网络0、发信0，覆盖全部失败、部分失败、旧值恢复、缺基线、真零、非零、恢复重跑、币种和别名。网站/HTML邮件预览检查了字段状态、小额价格、榜内唯一性和390px显示，未发现请求或脚本错误。

最终公网浏览器核实时间戳精确匹配12:31:31Z：LightMake在首页live榜、表格、统计榜及latest邮件各模块均仅一次；官方ID/alias证据可追溯，实际档位HKD8610按平台汇率折为$1,097.11。970项目、覆盖分母、9待确认及paused/enforce均与JSON一致。三页390px文档宽均390；HTTP错误、请求失败、console与JS错误均为0。公网projects JSON、API today、latest HTML、stats及app.js字节与仓库一致。

截图：[最终首页](ks-production-home-final.png)、[最终邮件预览](ks-production-email-final.png)。

关键文件：`scraper/{observations,quality,money,identity,graphql,refresh,project,run,momentum,diff,anomalies,weekly,report,email_notify,api,atomic,social}.py`；`site/{app.js,stats.html,corrections.html}`；`.github/workflows/{scrape,scrape-retry,test,deploy}.yml`；`scripts/{dry_run,build_corrections,currency_probe}.py`及相关回归测试。各PR提供完整差异。

## 当前边界与后续处理

- 仍有8个prelaunch与1个live项目未返回当前官方数据，完整列表见JSON。这些记录明确未更新/待确认，保留旧观测时间、继续计入覆盖分母，不能推断已删除或真实零增长。
- 可信日基线需要18–30小时观测间隔，周基线需要6.5–7.5天；连续同日重跑不能产生这些证据。下一个定时运行也不保证立刻满足日窗口。
- 生产变量维持`KS_EMAIL_DELIVERY=paused`、`KS_QUALITY_POLICY=enforce`。核心新鲜覆盖≥90%、日基线覆盖≥80%、观测≤30小时；可比样本≥20且≥95%零变化需复核。阈值是初始工程门槛，依据与局限见原排查报告。
- 达标后再由所有者确认恢复发送。此次没有测试真实投递及Gmail/Outlook客户端，HTML预览不代替客户端实发验收。
