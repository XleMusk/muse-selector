# Muse Selector 未完成路线执行计划

## 目标和当前判断

这份计划承接 `muse_like_execution_blueprint.md` 的 W2–W12，不重新设计已经可运行的只读 MVP。执行原则是：一条主关键路径、多个独立 Pod 并行、每天合入主线、每个节点产出可运行 artifact；外部凭据等待期间继续完成所有本地工作。

当前已经具备 W0/W1/W5 的完整主线，W2/W4 的核心连接器与硬过滤，W7/W9/W10 的部分能力。最新基线为 187 项测试通过、`hard_constraint_violation_rate=0.0`、CI 通过。仍未完成的重点是：W2 真实 eBay smoke、W3 质量报告、W6 完整状态图、W7 阈值事件、W8 只读浏览器、W9 兼容性矩阵和反馈、W10 故障演练、W11 灰度指标、W12 发布 Runbook。

## 四波执行路线

### Wave A：数据质量、检索和真实来源门

这波立即并行，不等待 eBay keyset。

| 工作包 | 主责 | 交付物 | 退出条件 |
|---|---|---|---|
| W2-REAL eBay 真实只读 smoke | P2 来源与连接器 | Sandbox/Production smoke 记录、脱敏字段快照、失败分类 | OAuth 和 Browse 请求均命中官方端点；真实响应能生成结果卡；凭据不进入日志、fixture 或 Git；失败仍 `source_unavailable` |
| W3 实体与质量 | P3 数据质量 | GTIN/EPID → MPN/SKU → 品牌型号的确定性键、去重报告、TTL/陈旧报告 | 重复率可计算；未知字段不补写；过期记录不进入推荐；报告可由 fixture 重放 |
| W4 检索基线 | P4 检索评测 | 结构化召回、硬过滤、排名指标和价格复算报告 | `hard_constraint_violation_rate=0`；Recall/Precision/NDCG/Jaccard 不回退；eBay 返回顺序不被客户端重排 |

W2 的真实生产授权是唯一外部门。没有 keyset 时只完成合同、mock、脱敏 fixture 和失败路径，不能把 fixture 宣称为实时成功，也不暂停 W3/W4。

### Wave B：有状态运行时和观察任务

| 工作包 | 主责 | 交付物 | 退出条件 |
|---|---|---|---|
| W6 单任务状态图 | P5 运行时 | `Parse → FanOut → Normalize → Filter → Rank → Verify → Present` 状态记录、checkpoint、暂停/恢复/重放 | 同一输入重放结果一致；崩溃后从最近 checkpoint 恢复；每个 stage 只有一个幂等 run；不依赖模型也能规则降级 |
| W7 观察任务增强 | P5 + P8 | 价格/库存/配送阈值、SQLite 本地事件 outbox、事件去重键、异常自动暂停 | 相同 `watch_id + event_key` 只产生一次事件；重启后可恢复；通知先保留为本地读取，不连接邮件、短信或平台写接口 |

已有 `watch_changes`、`last_change_summary` 和本地重放作为基础，先扩展状态和事件契约，再考虑任何外部通知。
当前已完成第一步：`watch_events` 持久化了 `price_max`、`stock_required`、`max_delivery_days` 的本地阈值事件，并通过 CLI `events` 和 Web `/api/watch/events` 只读读取；下一步仍是异常自动暂停和更完整的阈值跨越语义。

### Wave C：结果层、只读浏览器和红队恢复

| 工作包 | 主责 | 交付物 | 退出条件 |
|---|---|---|---|
| W9 用户结果层 | P7 结果层 | 硬件兼容性矩阵、证据展开、反馈事件写入 fixture、比较 artifact | 每个兼容性判断都能回到来源字段；反馈可重放进入回归集；没有来源证据的字段显示 `unknown` |
| W8 只读浏览器 | P6 浏览器安全 | feature flag 下的 accessibility-tree broker、固定官方域 allowlist、出口规则、人工接管状态 | 无登录、真实 token、任意 JavaScript、DevTools 或写动作；越权出口和不确定状态立即停止；W8 不阻塞 API MVP |
| W10 红队与恢复 | P6 + P8 | OAuth/429/超时/坏 JSON/损坏 checkpoint/重复 refresh 故障注入，SSRF、提示注入、token、跨租户测试集 | 凭据泄露、SSRF、越权出口、未审批写、重复副作用均为 0；每类故障都有可重放结果和回滚方式 |

浏览器路径只允许在隔离 mock 和官方测试域上推进。它的 feature flag 默认关闭，直到 W10 的安全退出条件满足。

### Wave D：灰度、运行手册和 Go/No-Go

| 工作包 | 主责 | 交付物 | 退出条件 |
|---|---|---|---|
| W11 限定灰度 | P8 评测运维 | fixture/模拟负载与一来源只读灰度报告，p50/p95、失败率、纠错率、成本、回滚演练 | 指标可观测；来源失败可熔断；回滚开关可用；只扩大读取，不扩大写权限 |
| W12 发布决策 | P0 集成 | Runbook、数据保留/删除流程、事故响应、连接器停用流程、下一阶段 backlog、Go/No-Go 记录 | G0–G6 每项都有文件或命令证据；未满足项明确延期或删除；没有用“模型效果不错”替代安全和数据门 |

W11 先做合成负载和单一官方来源的 shadow 运行，真实用户灰度必须等 W2 真实 smoke、W10 红队和 W11 回滚证据全部齐备。

## 并行边界和角色

- P0 只负责契约合并、主分支、feature flag、CI 和发布证据；不让多个 Agent 同时改变同一字段语义。
- P2 负责 eBay 条款、OAuth、Browse 字段、限流和停止开关。
- P3 负责实体键、去重、TTL、未知字段和质量报告。
- P4 负责硬过滤、排名基线、价格复算和评测集。
- P5 负责状态图、checkpoint、观察任务和幂等。
- P6 负责浏览器出口、提示注入、SSRF、token 和人工接管。
- P7 负责结果卡、兼容性矩阵和本地反馈。
- P8 负责故障注入、指标、回归和 Runbook。

Wave A 的 W3/W4、Wave B 的 W6/W7、Wave C 的 W8/W9/W10 可以并行；W6 只依赖已冻结的 W1 契约，W7 依赖现有 SQLite，W10 依赖安全策略和各模块的 mock 接口。W11 依赖 W10，W12 依赖 W11。W8 不得成为 eBay API 主线的前置条件。

## 每个节点的合入规则

1. 先提交一个可运行的最小 artifact 和对应回归样例。
2. 运行定向测试、全量测试、离线回归和 `git diff --check`。
3. 通过后提交、推送、等待 GitHub CI；CI 失败只修复根因，不扩大范围。
4. 结果必须记录输入契约、输出文件、退出条件、回滚开关和当前未验证项。
5. 任何涉及登录、购买、账号转移、支付、发信或平台写操作的能力保持 deny，不进入本路线。

## Go/No-Go 最低条件

允许继续扩大只读范围的最低条件是：真实 eBay 只读 smoke 通过；字段证据覆盖率至少 95%；硬约束违规率为 0；重放和观察事件幂等；SSRF、提示注入、token 泄露、跨租户读取和未审批写为 0；p95、失败率、纠错率和回滚均有基线。任一条件不满足，就缩小范围或保持当前只读版本，不把未完成能力挂到默认路径。
