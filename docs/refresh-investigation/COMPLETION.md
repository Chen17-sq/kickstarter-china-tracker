# 全面补齐：平台汇率、奖励分页与历史勘误

后续真实验收发现，上一轮保守接受显式USD留下的缺口可以继续修复。

Kickstarter官方Android客户端[schema定义](https://github.com/kickstarter/android-oss/blob/master/app/src/main/graphql/schema.graphqls)明确提供Project.currency、usdExchangeRate、Money.amount/currency，以及rewards分页信息；usdExchangeRate目标为USD，访客fxRate的目标币种随用户设置改变。代码现在使用显式USD汇率，不使用访客fxRate，也不从历史金额反推比例。

- 目录同时刷新项目币种、USD汇率、原币筹款和目标金额；USD值附原币金额、币种、汇率、来源和观测时间。
- 跨币种筹款增量采用当前平台汇率乘以可比的原币增量，不把汇率波动算成筹款增长。只有原币、口径、时间窗口可比才计算。
- 最低奖励档位使用项目汇率转换，并检查所有分页；缺页、循环游标、失败、无汇率都不能把局部最小值当作完整最低档位。完整空列表标“暂无档位”。
- 统计页移除已废弃的公开订阅者文件请求，展示实际发送策略；订阅名单继续保存在私有系统。日历天数改称追踪天数，不再当作已发邮件期数。
- 153份原日报新增独立的逐日勘误索引，原刊／快照均保留。带日志的日期标采集不完整，其余标观测证据不足，不推定全部数据源失效。

## 复现

```sh
.venv/bin/python -m pytest -q
.venv/bin/ruff check scraper scripts/currency_probe.py scripts/build_corrections.py
.venv/bin/python scripts/build_corrections.py
.venv/bin/python scripts/currency_probe.py --output /tmp/new-currency-probe.json
```

五种隔离回放可单独复现（输出目录必须新建；脚本强制阻断网络与发信）：

```sh
replay_root=$(mktemp -d /tmp/ks-replay.XXXXXX)
for scenario in all-failed partial healthy recovery currency; do
  .venv/bin/python scripts/dry_run.py --scenario "$scenario" --output "$replay_root/$scenario"
done
```

最后一项只读探针最多一条公开GraphQL查询，查询三种已有项目币种，不使用邮件、生产数据写入、保存会话或代理发现；失败状态不等于源恢复。原来四种禁网／禁发信隔离全链路回放继续由测试执行；新增currency场景验证全链路汇率变化：原币不变为$0，Fixture01总额$1093.04但可比筹款增量仅$53.04，缺原币基线仍无法计算。五种场景网络请求与发送均为0。

无保存会话的runner只读币种探针（run 37614450157）在浏览器seed阶段不可访问，查询0；绿色表示诊断完成，不能证明真实接口成功。生产仍需通过已获授权的refresh_only运行验收。

补充完整性保护：API日期快照与社交图同日重跑也另存内容摘要修订版，API索引不会将corrections.json误列为日期；社交图先在临时目录全部渲染成功，再发布latest，渲染失败保留旧版。未确认的active状态计入原分母并明确提示，超过10%会触发质量门槛。

本地最终回归309项通过，包含五种隔离全链路回放。浏览器验证首页、专项邮件、stats、153项勘误、归档索引：390px无溢出，跨币种样例正确，stats已暂停且不再读取订阅名单。

最终展示审计还修复了Markdown精选卡片、紧凑榜单和网站头版小计绕过观测契约的问题。最低奖励价格保留两位小数，缺失／暂无档位也明确展示。陈旧Fixture03的金额和档位均为未更新，旧金额只出现在明确参考文案；状态标待确认。原404已由HTTP日志确定为favicon.ico，补齐图标后全量监听4xx、console、JS异常均为0；首页与邮件390px复测通过。

## 真实生产验收（11:58 UTC）

[PR #9](https://github.com/Chen17-sq/kickstarter-china-tracker/pull/9)已合并为`ee49c69`，五项CI通过。用户授权的[不发信刷新](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37616410548)成功，快照`2026-10-07T11:58:12Z`，提交`a476329`。Email与Slack/Discord步骤均skipped；生产保持paused/enforce。

| 指标 | 10:43 UTC第一次恢复 | 11:58 UTC补齐汇率后 |
|---|---:|---:|
| 预热关注新鲜 | 220/228 | 220/228 |
| 在筹支持人数新鲜 | 150/151 | 150/151 |
| 在筹USD筹款新鲜 | 85/151 | 150/151 |
| 在筹最低档位新鲜 | 10/151 | 150/151 |
| 核心可比日增量 | 0 | 0（时间窗口尚不足） |

实际转换包含HKD、GBP、SGD、CAD、JPY、EUR及显式USD，逐字段核对原币×汇率全部一致。632个既有历史文件SHA256全部保持一致，新增1份采集快照及独立报告/API/图像修订版。机器可读证据见[completion-acceptance.json](completion-acceptance.json)。

本次验收还发现18个`STARTED`项目关注数据新鲜但状态未映射。官方ProjectState定义明确为“Created and preparing for launch”，现补充映射prelaunch；PURGED按官方隐藏暂停含义映射suspended，并保存本次raw_state。全部8种官方状态和未知状态均增加回归，未知状态继续保留旧时间，不能把字段成功当作状态刷新成功。此补漏后测试为318项通过。

## 官方项目身份与别名排重

公网浏览器发现LightMake L4以`lightmake`和`968766790`两个creator路径重复出现在Top10。仅同标题/金额/slug不足以合并；官方页面单次访问返回403挑战后停止。官方schema另有明确的`Project.pid: Int!`与`url: String!`，目录现采集这两个字段，Discover保留官方`id`，只有带来源与观测证据的相同项目ID才合并。

- 最新项目目录按确认的独立项目统计，原路径留在每行`aliases`和顶层`project_aliases`，原历史文件不改写。
- 官方URL对应的已有记录优先作为主路径，指标逐字段保留成功观测；缺ID、未知身份或不同ID即使同标题也不合并。
- 网站、邮件、API、质量分母均读取相同独立项目目录。日/周基线接受已确认别名，拒绝已知不同ID；日报差分与异常检查不再将别名迁移当作新增/消失。
- 新增第六种`aliases`隔离全链路回放：31个历史路径保留为30个独立项目和1个别名，核心live分母15，正常增量仍29项有效，网络/发信0。新增身份单元与整链路回归后330项通过。

```sh
.venv/bin/python scripts/dry_run.py --scenario aliases --output /tmp/ks-aliases-new
```
