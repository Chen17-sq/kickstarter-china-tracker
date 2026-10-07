# 验证记录

- Python 3.12.14；`python -m pytest -q`：**281 passed**（含4次隔离全链路回放）。
- `ruff check scraper scripts/dry_run.py scripts/audit_refresh_history.py`：通过。
- `python -m compileall -q scraper`、`git diff --check`：通过。
- scrape / scrape-retry / email-only / test workflow YAML：本地解析通过。
- `git diff --quiet -- data reports assets site/editions site/api site/weekly site/social`：通过；生产快照、旧日报及发布产物未修改。
- 四次回放的计数见 `offline-results.json`；每次运行在新建目录，socket连接与邮件发送被强制拒绝，实际请求0、发送0。恢复场景保留4份历史（7天前、昨日、今日失败、今日恢复）。

## 浏览器

使用 expect skill 的独立浏览器验证，在 `127.0.0.1` 查看隔离样例：

- 搜索 Fixture 00/01/02/21，分别验证真实 $0、+$51 且关注失败、筹款基线缺失、全部旧值。
- 网站/邮件状态与金额一致；旧值展示原观测日期，缺基线显示“无法计算”。
- 全部失败页面有效覆盖0/15，没有把未知差额显示成0；恢复后 Fixture01 日筹款+$51。
- 中/英文切换和搜索正常。390px窄屏网站及专项邮件文档宽度均为390px；统计页也通过390px检查，数据请求均200且console error=0。
- 无数据加载或应用JavaScript错误；浏览器预览不能替代真实Gmail/Outlook客户端验证。
- 最小a11y检查：新状态含明确文字，不依赖颜色；质量区域使用h2。全站旧样式的完整无障碍认证不在本次修复结论内。
- 初次预览曾发现邮件局部变量误打印字典、移动溢出、中英文状态文案混用及stats最低档位陈旧显示；均针对性修正后复测。

- README三个SVG与社交卡片浏览器复测通过：降级标识可见，旧字段未更新；部分失败样例仍保留新鲜筹款合计。顶部合计也失效的分支由回归测试覆盖。

截图 `email-mobile.png` 使用合成Fixture，无真实订阅者资料。

## 在线验证边界

只读浏览器访问 Kickstarter Discover 得到200及CSRF meta，但一条公开项目GraphQL查询仍为403挑战页。没有运行生产采集、没有部署、没有发信、没有修改账号或挑战状态。不能把离线回放的成功覆盖率解释为生产采集已恢复。

第二轮多批次、已知项目覆盖、基线恢复、真实runner浏览器与只读源诊断见[继续修复记录](CONTINUED-REPAIR.md)。

GitHub runner真实浏览器fixture：[通过记录](https://github.com/Chen17-sq/kickstarter-china-tracker/actions/runs/37606495758)。两种浏览器各连续查询2次，nodriver loop_closed=true；Kickstarter普通源探针仍为403，不属于采集恢复证明。
