# 第二轮全面修复（2026-10-07）

本轮继续定位了第一轮遗漏的批次、浏览器实际协议、覆盖和基线问题。变更继续位于 PR #7，未合并、未部署、未改生产快照、未发信。

## 新证据：目录成功数始终等于最后一个不足 50 项的批次

对 9/1–10/7 的历史日志再次核查：**19 个返回过 catalog 数据的运行，返回对象数全部等于请求总数 % 50**。例如 782→32、907→7、943→43、963→13。其余 16 个完成运行返回 0。原始对象数与 apply 后的记录数有时不同（例如43对象/45记录），因为已有路径包含相同项目slug；没有自动删除或合并历史身份。

逐日数据已加入 `historical-refresh-summary.json` 的 `positive_catalog_batches`。这强烈指向完整50项批次与短尾批的差异；旧实现没有记录 GraphQL errors，不能将具体的服务端 complexity 阈值写成已证实事实。

修复：

- catalog 独立每批20项，避免直接沿用单字段 watchers 的50项配置。
- HTTP200/400只有明确 complexity/cost/alias-limit 错误才在固定请求预算内拆分；普通schema错误不会无限重试。
- 记录每批 requested、returned、错误类别。字段级 GraphQL 错误仅使对应字段失效，成功兄弟字段保留；全局错误不能冒充成功。
- 401/403/429使当前共享会话停止后续请求，不靠缩小批次或新身份继续请求。
- 943项和整除批次回归确保保留所有批次结果，防止仅测30项fixture掩盖大目录故障。

## 新证据：真实 nodriver 与模拟对象不相同

新增 GitHub `browser-lifecycle` job，在 runner 本机HTTP fixture上验证真实Playwright和nodriver，各连续查询两次并关闭。没有访问Kickstarter、生产数据或邮箱。

实际执行暴露了：

1. Playwright下载的浏览器可由Playwright启动，却不能稳定由nodriver直接启动；采用runner已有Chrome后曾成功启动和获取fixture CSRF。代码现在显式选已安装Chrome，并保留浏览器sandbox。
2. nodriver 0.50.5的 `Tab.evaluate()` 默认深度序列化JS对象；返回结构不保证是Python dict。原实现直接要求dict，所以启动成功后查询仍会失败。现改为JS显式JSON.stringify、Python显式解析。
3. nodriver自身启动代码只等待约3秒。现在自行拥有临时profile和进程，等待DevToolsActivePort就绪（最多30秒）再通过公开host/port接口连接；整个启动最多60秒，查询最多30秒，失败也清理进程与临时目录。

4. 导航返回可能早于新DOM就绪；现在等待目标meta出现（最多5秒），避免读取about:blank后误报缺CSRF。

[真实runner验证](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37606495758)已通过：Playwright与nodriver各完成两次本机fixture查询，nodriver事件循环关闭；摘要见`browser-probe.json`。

第1、3点属于运行环境兼容和启动可靠性修复，不等于证明过去每次 `Failed to connect to browser` 都由同一个原因造成。

## 全链路补漏

- 先刷新已知目录核心字段，再查询缺失watchers和最低档位。范围包含Discover没返回的已知live/prelaunch项目；不会让它们的奖励档位永久停留在旧值。
- 日／周增量逐字段从窗口内全部尝试选择有效观测；最近的失败尝试不会遮住稍后的有效基线。
- 已过期的valid delta不能继续计入可比覆盖。每支持者筹款派生指标也需要新鲜数据。
- 访客币种换算金额不再标为项目静态汇率口径，避免不同汇率口径跨源计算增量。
- Slack/Discord摘要及AI编辑上下文同步展示未更新。AI草稿绑定snapshot_at；旧快照草稿、质量不完整时的草稿不会混入新一期邮件。
- 新增仓库变量接线：`KS_QUALITY_POLICY=observe|enforce`、`KS_EMAIL_DELIVERY=paused`。默认仍observe；没有设置或修改生产仓库变量。email-only也尊重暂停变量；CLI设置同名环境变量时在读取/归档/查询收件人之前暂停。enforce同样适用于legacy快照，不能通过旧schema绕过质量门槛。

## 真实源访问与剩余边界

[只读源诊断](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37605402009)在GitHub runner发出1次普通Discover GET，返回HTTP403 HTML后停止。`source-probe.json`记录`source_access_unavailable`，发送0。该job绿色只表示完成诊断，不表示数据新鲜或生产恢复。

该诊断使用普通HTTP客户端，不代表所有现有来源/客户端都失败；历史Discover仍有成功筹款变化。没有新建代理、借用登录态或绕过挑战。

还需在可正常访问官方数据的运行环境／授权接入上，进行受控的真实多批次采集验收。第三方历史快照或RSS发现信息不能自动替代当天followers或筹款观测。

## 上线顺序（待用户确认，未执行）

1. 确认生产质量策略。建议迁移验收期间设`KS_EMAIL_DELIVERY=paused`，同时设`KS_QUALITY_POLICY=enforce`；默认观察模式保留在代码中，避免擅自改变现有生产策略。
2. 合并、部署PR前保留当前提交和快照。首次只运行`refresh_only=true`；该步骤会更新生产数据，所以须另行批准。
3. 检查每批源诊断、字段新鲜覆盖、失败原因，确认不会仅成功尾批。403仍存在时保留未更新状态，先解决授权数据接入／运行环境，不能把绿CI当作恢复。
4. 日增量需两次约24小时相隔的有效观测；周增量需约7天。历史无观测时间的旧格式不充当可信基线。达到已确认门槛后再解除发送暂停。
5. 对历史日报只增加勘误索引或带版本修订，不覆盖旧证据；是否发送勘误另行确认。

## 回归与预览

- `python -m pytest -q`：281通过，包含全部失败、部分失败、旧值恢复、缺基线、真零、非零、重跑和本轮多批次/错误范围/基线选择回归。
- 四次隔离回放继续强制禁网、禁发信；生产projects.json哈希保持一致。
- 第二轮浏览器：Fixture20（Discover遗漏）最低档位新鲜$10；Fixture21旧值未更新且保留10/6观测；Fixture01筹款+$51、关注失败。专项邮件与网站一致，390px无横向溢出、console error=0。
- 诊断命令：`python scripts/refresh_probe.py --mode browser --output /tmp/new-browser-probe.json`；`--mode source`运行只读源诊断。output必须是仓库外不存在的新文件。
