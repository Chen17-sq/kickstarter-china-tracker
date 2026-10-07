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

最后一项只读探针最多一条公开GraphQL查询，查询三种已有项目币种，不使用邮件、生产数据写入、保存会话或代理发现；失败状态不等于源恢复。原来四种禁网／禁发信隔离全链路回放继续由测试执行；新增currency场景验证全链路汇率变化：原币不变为$0，Fixture01总额$1093.04但可比筹款增量仅$53.04，缺原币基线仍无法计算。五种场景网络请求与发送均为0。

无保存会话的runner只读币种探针（run 37614450157）在浏览器seed阶段不可访问，查询0；绿色表示诊断完成，不能证明真实接口成功。生产仍需通过已获授权的refresh_only运行验收。

补充完整性保护：API日期快照与社交图同日重跑也另存内容摘要修订版，API索引不会将corrections.json误列为日期；社交图先在临时目录全部渲染成功，再发布latest，渲染失败保留旧版。未确认的active状态计入原分母并明确提示，超过10%会触发质量门槛。

本地最终回归307项通过，包含五种隔离全链路回放。浏览器验证首页、专项邮件、stats、153项勘误、归档索引：390px无溢出，跨币种样例正确，stats已暂停且不再读取订阅名单。
