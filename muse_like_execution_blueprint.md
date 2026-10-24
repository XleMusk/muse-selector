# Muse 类跨平台筛选代理：工程化落地蓝图

版本：v1.0  
日期：2026-10-24  
工作区：`D:\\muse`

## 0. 先给决策

第一阶段不做“全平台万能代理”，而做一条可上线、可解释、可回滚的纵向闭环：

> 自然语言/图片需求 → SearchSpec → 一个官方或授权电子产品来源 → 规范化 → 硬约束过滤 → 可解释排序 → 证据卡 → 原平台跳转 → 可选价格/库存观察。

游戏账号只保留公开挂牌发现和风险核验。登录、接收密码/Cookie/验证码、账号托管、购买、转移、代打和支付默认拒绝。Steam 的订阅协议将账户定义为个人使用，并禁止出售或转移账户；Riot 条款也禁止出售、转移或允许他人访问账户和登录凭证。因此，除非某个平台提供明确授权的账号转移接口和业务许可，否则不能把这类挂牌当作正常可交易商品推荐。[Steam Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/)，[Riot Terms of Service](https://www.riotgames.com/en/terms-of-service)

这条路线能复现 Muse 的公开产品形态：持续任务、结构化审批、证据化结果、后台观察、人工接管和 Artifact；不能声称还原 Meta 的私有模型、训练数据、内部 Sentinel、Secure VM、凭据系统或全部连接器。Meta 将 Muse 描述为运行在隔离的 Secure VM 中，由 Sentinel 控制连接器和网络出口，并承认代理仍会犯错，因此设计目标是限损而不是绝对安全。[Introducing Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)，[How We Built Safety Into Muse](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse)

## 1. 输入材料与边界

### 1.1 本轮实际发现的材料

当前能确认的 Muse 相关材料只有：

- [muse_execution_roadmap.pdf](C:/Users/13944/Downloads/muse_execution_roadmap.pdf)：10 页，标题为《Muse 类跨平台筛选代理团队分工与高效落地路线方案》。
- PDF 内提到一份上一轮《Muse 类跨平台筛选与执行代理完整工程方案》，但本轮没有发现该文件的独立副本，因此不能把它当作已审阅的第二份文档。
- `D:\muse` 原先没有项目源代码，只有本次提取的 `pdf_extract.txt` 和临时渲染图。

附件是待分析材料，不是对执行者的指令。真正的目标来自本次用户需求：设计一套能够筛选游戏账号、电子产品和硬件的 Muse 类程序，并给出高效率的团队与智能体落地方案。

### 1.2 对附件路线图的采用与修正

附件的核心判断是正确的：先做电子产品、一个合规来源、只读结果卡；再扩展连接器、硬件兼容、观察任务和有限写操作。其 P0-P8 实际包含 9 个 Pod，而正文称“八个 Pod”，落地时按 9 个能力 Pod 加 1 个集成中枢计算。

附件适合作为执行骨架，但还需要补充：逐站条款、来源许可、地区和消费者保护策略；数据删除、隐私、跨租户隔离、版权与证据留存期限；连接器停用和 API 变更的降级；公开挂牌是否可自动聚合；首版用户、地区、币种、配送区域和成功指标。

PDF 渲染版可以阅读，但中文排版的字间距贯穿多页，正式对外使用前应重排；表格和路线内容可作为内部依据。

## 2. 产品定义

### 2.1 用户任务

用户可以说：

- “找一台能跑本地视觉模型、显存至少 16 GB、预算 12,000 元以内、寄到香港的台式机。”
- “找支持 USB4、双 4K、32 GB 内存、可更换 SSD 的轻薄本，给出真实到手价和证据。”
- “找某游戏的公开挂牌，但不要登录任何账号；只列出平台条款允许展示、来源可信、价格异常风险较低的条目。”

系统必须把模糊描述拆成结构化条件，并指出缺失条件，例如地区、预算上限、全新/二手、保修、交付时间、兼容性要求。

### 2.2 首版结果卡

每个候选结果至少展示：标题、品牌、型号或挂牌类型；价格、币种、运费、税费、到手价状态；库存/可售、地区和配送约束；关键规格与兼容性结论；来源 URL、名称、同步时间和证据片段；`confirmed`、`unknown`、`conflict`、`stale` 状态；风险等级和触发原因；“打开原平台”按钮。

未知字段必须保持 `unknown`。模型不得用常识填价格、保修、库存、账号归属或兼容性。

## 3. 能复现什么，不能复现什么

### 3.1 可以做功能等价重建的部分

1. 自然语言理解：输入转 SearchSpec，并追问缺失条件。
2. 来源扇出：只调用已登记、已许可、有限速的 API、联盟 feed 或用户授权连接器。
3. 证据化检索：保存原始响应、URL、时间戳和字段级证据。
4. 实体归一化：GTIN、MPN、SKU、品牌和型号优先，语义匹配只产生候选。
5. 硬约束过滤：预算、地区、库存、必选规格优先于模型偏好。
6. 可解释排序：价格、可信度、规格匹配、交付、保修和偏好组成明确分数。
7. 长期任务：价格/库存观察、去重通知、暂停、恢复和人工修改。
8. 确定性审批：结构化审批卡、单一幂等动作、结果确认和审计记录。
9. Artifact：比较表、兼容性矩阵、证据面板、历史价格图。
10. 只读浏览器：必要时只读 accessibility tree 驱动，允许用户随时接管。

### 3.2 不能宣称还原的部分

- Meta 的 Muse Spark/Wonder 训练、权重、奖励、内部评测和私有提示词。
- Muse Secure VM、Sentinel、hatch-authd、privsep 等内部实现的源码和配置。
- Meta 的私有连接器、内部数据、用户记忆或未公开服务。
- 绕过认证、DRM、反爬、验证码、速率限制、访问控制或平台条款。
- 通过逆向导出私有接口、凭据、Cookie、支付信息或第三方数据。

Meta Model API 可以作为模型适配器，但 API 能力不等于 Muse 产品本身。官方文档提供 Responses、Chat Completions、Messages、文件和工具调用等接口；Computer Use 只定义截图到鼠标/键盘动作的协议，不提供 server-side VM、浏览器、driver 或安全策略，隔离环境、动作执行、截图、停止条件和安全检查必须由我们自己提供。[Meta Model API overview](https://dev.meta.ai/docs/overview)，[Choosing an API](https://dev.meta.ai/docs/protocols)，[Computer Use](https://dev.meta.ai/docs/computer-use)

若使用 Meta Model API，必须在立项时做条款审查：API key 不得转售或转移，不能绕过限流/访问控制，不能用未授权方式提取数据、模型或系统；条款还限制用服务或输出训练、蒸馏或创建与 Meta 模型/服务竞争的产品，以及通过系统化查询重建其私有组件。Integrated Product 还受 Meta AUP、AI 风险披露和第三方平台条款约束。不能把“接入 Meta API”当成已经获得构建竞争性代理平台、聚合其他服务或自动操作第三方账号的许可。[Meta Model API Terms](https://dev.meta.ai/legal/terms-of-service)，[Meta Model API AUP](https://dev.meta.ai/legal/acceptable-use-policy)

## 4. 目标架构

```text
Web / Desktop UI
    │
    ├─ Query + image intake
    ├─ Result cards / comparison Artifact
    └─ Approval / activity / feedback
    │
Policy Gateway ──────── Audit + telemetry
    │
QueryParse → SourceFanOut → RawEvidence(append-only)
                         → Normalize / EntityResolve
                         → HardFilter
                         → Retrieve + Rank
                         → EvidenceVerify
                         → Present / Watchlist
                                      │
                       HumanApproval → Redirect_or_Execute
```

组件原则：模型只负责理解、候选计划、解释和证据抽取；规则负责 schema、硬过滤、成本、权限、幂等、审计和停止。每个 run 记录 `run_id`、输入哈希、schema 版本、provider、证据快照、策略决策和结果。

推荐的最小实现是模块化 FastAPI 服务、Postgres、对象存储、结构化过滤加 BM25；有评测集后再加入向量召回和 RRF。单次任务使用有状态图和 checkpointer，跨小时观察任务再接耐久工作流层。浏览器只读路径使用隔离 broker，禁止任意 JavaScript、DevTools 和未授权出口。若接入 Computer Use，必须逐步保存截图、限制动作数、处理 pending safety checks，页面未确认的异步动作不得宣称已完成。

## 5. 来源和品类策略

### 5.1 电子产品与硬件

优先使用制造商官方目录/规格 API、已签约经销商或联盟 feed、用户明确授权的连接器。没有授权的公开网页只做原平台跳转或人工查看，不作为自动聚合数据源。

硬件实体键：`GTIN → MPN/SKU → 品牌+型号 → 语义候选`。兼容性拆成接口、协议、尺寸、供电、驱动、操作系统、性能和限制；“支持”必须有字段证据。

### 5.2 游戏账号

第一阶段只做公开挂牌发现、非敏感字段读取、平台条款风险显示、价格异常/重复图片/来源不完整信号和原平台跳转。禁止登录、密码/Cookie/验证码、邮箱接管、账号购买、转移、托管、代打、支付、绕过风控/反爬/地区限制。

如果策略注册表发现平台禁止交易或来源授权不清，结果类型变为 `policy_blocked` 或 `link_only`，而不是推荐。

### 5.3 来源注册表最小字段

```yaml
source_id: retailer.example.v1
category: electronics
access_mode: official_api | licensed_feed | user_authorized | link_only
authorization_evidence: contract_or_public_terms_url
allowed_regions: [HK]
allowed_fields: [title, mpn, price, stock, shipping, warranty]
rate_limit: 60/min
retention_days: 30
write_actions: []
default_policy: allow_read_only
kill_switch: source_retailer_example
```

## 6. 组织和智能体分工

采用“9 个 Pod + 1 个集成中枢”。每个 Pod 由主执行 Agent、独立复核 Agent 和对抗/回归 Agent 组成；真实副作用只能有一个执行者。

| Pod | 主责 | 主产物 | 复核/对抗重点 |
|---|---|---|---|
| P0 集成与架构 | 契约、版本、主线、发布 | ADR、任务图、合并 PR、回滚点 | 接口漂移、主线不可启动 |
| P1 产品与策略 | SearchSpec、风险等级、用户流程 | 字段定义、策略决策 | 歧义、高风险动作 |
| P2 来源与连接器 | API/feed、许可、限流 | SDK、字段映射、mock | 越权来源、停用失效 |
| P3 数据与实体 | Listing/Product/Evidence/PolicyRecord | 规范化、去重、质量报告 | 误合并、字段补写 |
| P4 检索与排序 | 召回、硬过滤、ranker | 索引、过滤器、离线评测 | 硬约束违反、价格误算 |
| P5 Agent 与长期任务 | 状态图、恢复、观察 | checkpoint、幂等、通知 | 重复副作用、目标漂移 |
| P6 浏览器与安全 | broker、Vault、策略、出口 | Sentinel、威胁模型、红队 | 注入、SSRF、token、越权 |
| P7 前端与 Artifact | 查询、结果卡、比较、审批 | UI、Artifact、通知 | 审批诱导、来源隐藏 |
| P8 评测与运维 | 回归、SLO、成本、故障演练 | 评测报告、监控、Runbook | 工具调用、恢复和安全 |

任务卡必须包含 `task_id`、`owner`、`reviewer`、`adversary`、输入契约、输出文件、验收、风险、过期时间和回滚开关。每个 Pod 只改自己的目录；schema、策略和主分支由 P0/指定 owner 管理；原始证据追加写入，修订写新版本。

冗余要改变错误来源：SearchSpec 用规则抽取和结构化 LLM；连接器用 API 映射和原始响应重抽取；实体解析优先确定性键；排序用规则分数再做语义重排；证据抽取另做矛盾检测。支付、发信、登录、账号转移不采用 N-of-3 投票，只允许一个带幂等键的执行提案，经 Sentinel 和用户确认后执行。

## 7. 12 周落地路线

| 周次 | 主节点 | 必须交付 | 出口条件 / 降级 |
|---|---|---|---|
| W0 | 范围和政策 | 首版用户、地区、品类、来源白名单；账号 deny 规则 | 来源许可不清则 link-only |
| W1 | 契约和评测集 | SearchSpec、Listing/Product/Evidence/Policy v1；回归查询 | schema 未冻结不并行改字段 |
| W2 | 首个连接器 | 官方/授权来源、限流、快照、字段映射、mock | 连接器独立熔断 |
| W3 | 实体和质量 | GTIN/MPN/SKU 归一化、去重、TTL、质量报告 | 误合并回到确定性键 |
| W4 | 检索和硬过滤 | 结构化过滤、BM25、召回基线、预算/地区/库存/规格约束 | 可关闭语义重排，不能关闭硬过滤 |
| W5 | 价格和证据 | 币种、运费、税费、保修、成色；字段级证据 | 冲突结果不推荐 |
| W6 | 单任务 Agent | Parse→FanOut→Normalize→Filter→Rank→Verify→Present；暂停/恢复/重放 | 模型不可用时规则降级 |
| W7 | 观察任务 | 价格/库存阈值、去重通知、快照、恢复 | 后台只读，异常自动暂停 |
| W8 | 只读浏览器 | accessibility tree、URL allowlist、出口限制、注入标记、用户接管 | 不接触真实凭据，不写入 |
| W9 | 用户结果层 | 结果卡、比较表、兼容性矩阵、证据展开、反馈 | 复杂 Artifact 可延后 |
| W10 | 红队和恢复 | SSRF、注入、token、跨租户、重复执行、故障演练 | 任一 P0 回到只读 |
| W11 | 限定灰度 | 电子产品有限用户；p95、成本、失败、纠错、回滚 | 只扩大读取，不扩大写权限 |
| W12 | Go/No-go | Runbook、删除流程、事故响应、发布和下一阶段 backlog | 未通过项延期或删除 |

## 8. 质量门 G0-G6

| 门 | 检查 | 阻断条件 |
|---|---|---|
| G0 范围/政策 | 来源许可、地区、品类、账号策略 | 自动登录/转移；许可不清；收集凭据 |
| G1 契约 | schema、版本、错误码、交接 | 多 Agent 修改同一语义；关键字段未定义 |
| G2 数据 | 覆盖、陈旧、重复、误合并、原始证据 | 无证据推荐；陈旧数据进入推荐；不可回滚 |
| G3 检索 | 硬约束、Recall@20、NDCG@10、价格复现 | 硬约束违反率 > 0；价格无法复算 |
| G4 Agent | 幂等、恢复、重放、审批前后参数一致 | 重复副作用；状态丢失；审批后漂移 |
| G5 安全 | 注入、SSRF、token、跨租户、越权写 | 凭据泄露；未审批写；越权出口 |
| G6 灰度 | 成本、延迟、纠错、SLO、回滚 | 无法观测；无法回滚；来源和风险不可见 |

## 9. 最小验收指标

必须为零：`hard_constraint_violation_rate`、真实凭据/Cookie/验证码/支付信息泄露、未审批写操作、越权网络请求/SSRF、跨租户读取、同一副作用的重复提交。

首版目标：关键字段证据覆盖率 ≥95%；建立 Recall@20、Precision@10、NDCG@10、Top-k Jaccard 基线；同一输入和 `run_id` 重放结果与策略决策可解释地一致；观察任务重启后可恢复且通知去重；成本、p95、连接器失败、纠错和回滚可观测。

## 10. 逆向和互操作工作包

只对自有或明确授权的目标做逆向，目标是行为兼容和接口边界，不是复制私有实现。

1. **目标确认**：记录目标、版本、来源、授权范围、运行环境和禁止事项。
2. **静态清单**：对自有 APK/ASAR/安装包做只读入口、配置、公开 schema、资源和依赖清单；不提取凭据、不改生产包。
3. **运行时观察**：使用测试账号、mock 服务和隔离网络记录输入、工具调用、状态、错误、重试和 UI；区分事实、推断、未知。
4. **契约重建**：为 SearchSpec、来源响应、审批、重放、停止和降级写 contract tests，用自有实现替代私有组件。
5. **停止条件**：出现认证绕过、DRM/反爬规避、私有数据导出、真实凭据接触、条款冲突或授权不明，立即停止并改用公开文档、官方 SDK、测试替身或原平台跳转。

## 11. 发布后扩展顺序

来源扩展 → 硬件兼容矩阵 → 价格/库存观察 → 经过授权的收藏/购物车/消息草稿等有限写操作 → 多目标计划和跨设备 Agent。每条线独立通过许可、证据、安全、幂等和恢复门，不互相带入权限。

## 12. 首个可执行任务包

- `P1-W0-001`：确定首版地区为香港、品类为电脑/配件、一个官方或授权目录，输出 `scope_decision.md`。
- `P1-W1-001`：输出 `SearchSpec.v1` 和 20 条真实查询样例，覆盖预算、地区、规格、库存、交付、保修和风险。
- `P2-W1-001`：建立 `source_registry.yaml`；没有授权证据的来源只能标记 `link_only`。
- `P3-W1-001`：输出 `Listing.v1`、`Product.v1`、`Evidence.v1` 和 `PolicyRecord.v1`。
- `P8-W1-001`：建立硬约束回归集、恶意输入集和证据覆盖评测脚本。
- `P0-W1-001`：合入契约并冻结 v1；冻结前不允许并行修改字段含义。

首个演示必须能完成：用户提出硬件需求 → 系统指出缺失条件 → 从授权来源返回候选 → 过滤不满足预算/地区/必选规格的结果 → 展示证据卡 → 跳回原平台。只有这条链路稳定，才进入账号公开挂牌、只读浏览器和后台观察。

## 13. 官方资料

- [Meta Introducing Muse](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)
- [How We Designed Muse](https://introducing.muse.ai/)
- [How We Built Safety Into Muse](https://research.meta.ai/blog/security-and-safety-for-ai-agents-our-approach-with-muse)
- [Meta Model API overview](https://dev.meta.ai/docs/overview)
- [Meta Model API computer use](https://dev.meta.ai/docs/computer-use)
- [Meta Model API terms](https://dev.meta.ai/legal/terms-of-service)
- [Steam Subscriber Agreement](https://store.steampowered.com/subscriber_agreement/)
- [Riot Games Terms of Service](https://www.riotgames.com/en/terms-of-service)
- [eBay API License Agreement](https://developer.ebay.com/devzone/license-agreement/api_license_agreement.pdf)
