# Muse Selector MVP

中国大陆电脑/硬件二手市场是当前产品主线；香港 eBay 的 `EBAY_HK`
`item_summary/search` 适配层作为已验证的只读基线保留。本地开发和回归默认使用 fixture，不联网、不接收用户凭据、没有写操作接口。

## 中国大陆二手市场状态

当前 CN/CNY 查询已经进入 SearchSpec 和安全路由，但会在没有官方挂牌搜索授权时返回 `source_unavailable`。闲鱼公开合作方能力需要入驻、OAuth、逐项权限申请和相应部署条件；转转公开官方 MCP 当前提供商品识别、回收估价和回收入口，不提供通用挂牌搜索。

无官方挂牌搜索权限时，结果 JSON/Markdown 仍会给出 `link_only` 人工入口卡：包含官方平台入口、原始手动查询和只读说明。用户可以点击官方入口并在平台内自行搜索；系统不会抓取、排序、读取登录态或执行写操作。这是人工接管路径，不是 API 搜索结果。

因此，国内主线的第一步是获得官方搜索能力或合作方授权；系统不会使用 Cookie、私有接口、逆向签名或网页批量抓取来填补这个缺口。完整持续目标见 [PROJECT_GOAL.md](PROJECT_GOAL.md)，范围和验收见 [scope_decision.md](scope_decision.md) 与 [acceptance_matrix.md](acceptance_matrix.md)。

### 游戏账号市场

游戏账号是独立的国内只读领域。查询公开市场信息时，系统会返回 5173、淘手游和交易猫的官方人工入口，并保留预算、游戏和原始查询；系统不会抓取挂牌、读取登录态或代替用户完成交易。涉及登录、密码、验证码、购买、出售、转移、代打或支付的请求会返回 `policy_blocked`，并展示允许与阻断动作。

### 转转官方 MCP 估价辅助

转转官方 MCP 已接入为独立的只读辅助连接器。它通过官方 Streamable HTTP 网关调用 `recycle_valuation` 和 `open_recycle_entry`，用于识别商品、返回人民币回收区间或生成用户自行打开的回收入口；它不提供通用挂牌搜索，也不会代用户下单。

先在[转转开放平台 MCP 控制台](https://open.zhuanzhuan.com/mcp)完成手机号验证并取得 Token，再在 PowerShell 中执行一次性 smoke。Token 只从当前进程环境读取，不会写入结果或仓库：

```powershell
$env:ZHUANZHUAN_MCP_TOKEN = "<official-mcp-token>"
$env:PYTHONPATH = "D:\\muse\\src"
muse-zhuanzhuan-smoke --query "ThinkPad X1 Carbon，16GB，电池健康良好，成色良好"
```

追加 `--image-url` 可传入公开图片地址，最多 35 个；需要入口时可追加 `--open-entry`。没有 Token、Token 过期、权限不足或网关不可用时，命令返回 `source_unavailable` 和退出码 `2`，不会回退到网页抓取或 eBay。

官方字段契约和能力边界见[回收估价文档](https://open.zhuanzhuan.com/docs/zai-transfer-mcp/recycle-valuation)、[回收入口文档](https://open.zhuanzhuan.com/docs/zai-transfer-mcp/open-recycle-entry)以及[转转 MCP 总览](https://open.zhuanzhuan.com/mcp)。

## 直接运行

在 PowerShell 中从 `D:\muse` 执行：

国内主线示例（没有获得官方挂牌搜索授权时，会返回 `source_unavailable` 和人工入口卡）：

```powershell
muse-selector --query "国内预算 CNY 8000 以内的二手迷你主机" --format json
muse-selector --query "国内原神游戏账号，预算 CNY 500" --format json
```

公开仓库的版本 tag（例如 `v0.1.0`）会触发 [release workflow](.github/workflows/release.yml)，构建并验证 sdist/wheel，再把两个发行包附到 GitHub Release。首次发布前可以直接从源码安装；已有版本发布后可从 Release 安装 wheel：

```powershell
# 源码安装（当前仓库）
python -m pip install --no-deps git+https://github.com/XleMusk/muse-selector.git

# 已发布版本示例，把 v0.1.0 替换为目标 tag
python -m pip install https://github.com/XleMusk/muse-selector/releases/download/v0.1.0/muse_agent-0.1.0-py3-none-any.whl
```

如果要安装命令入口，可先执行一次：

```powershell
python -m pip install --no-deps -e D:\muse
muse-selector --help
muse-selector --version
```

安装后可以用离线 doctor 检查 Python、包导入和 fixture 端到端契约。它不会联网；凭据只输出 `missing`、`partial` 或 `present` 状态，不会输出凭据值：

```powershell
muse-doctor --fixture D:\muse\tests\fixtures\ebay_hk_sample.json
```

doctor JSON 带有固定的 `schema_version`（当前为 `muse.doctor.v1`）、`runtime` 段和 `ebay_target` 段。`ebay_target` 只报告当前目标环境、官方 API 主机和 OAuth 路径，不发起网络请求，也不包含凭据。拿 Sandbox keyset 做接口 smoke 前可显式指定环境：

```powershell
muse-doctor --environment sandbox --fixture D:\muse\tests\fixtures\ebay_hk_sample.json
```

省略 `--environment` 时沿用 `EBAY_ENVIRONMENT`，未设置则报告 production。也可以运行 `muse-doctor --version` 单独确认 doctor 入口版本。

省略 `--fixture` 时只检查本地 Python 和包导入，适合在已安装 wheel 或脱离源码目录的环境中快速确认命令入口。fixture 不存在、格式错误或结果契约不满足时返回退出码 `2`，成功返回 `0`。

### 香港 eBay 兼容基线

下面的 fixture、状态图和 eBay Browse 命令用于保留历史兼容适配器的回归能力，不代表国内产品默认来源。也可以不安装，使用下面的 `PYTHONPATH` 方式直接运行源码。

```powershell
$env:PYTHONPATH = "D:\muse\src;D:\muse\tests"
$env:PYTHONIOENCODING = "utf-8"

# 在 PowerShell 中把 JSON 重定向到文件时保留这个变量，确保中文结果按 UTF-8 写入。

python -m muse_selector `
  --query "香港预算 HKD 7000 以内的迷你主机" `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --format markdown
```

JSON 结果卡：

```powershell
python -m muse_selector `
  --query "香港预算 HKD 7000 以内的迷你主机" `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --format json
```

状态图入口会输出 `Parse → FanOut → Normalize → Filter → Rank → Verify → Present` 的阶段状态和可重放 checkpoint。checkpoint 现在包含 `muse.selector.stage-checkpoint.v1`、每个阶段的完成时间和稳定指纹；`FanOut` 阶段还会保存原始只读 rows 和来源元数据，来源请求中断后可从该阶段继续本地处理。可用 `--checkpoint-out` 原子保存到本地 JSON，进程重启后通过 `--checkpoint` 重放，重放时会校验阶段列表与指纹，不会再次调用连接器：

```powershell
muse-state-graph --query "香港预算 HKD 7000 以内的迷你主机" --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json"
```

把上次输出中的 `checkpoint` 保存为 JSON 后，可用 `--checkpoint` 重放同一个执行请求。

所有 pipeline、CLI JSON、live smoke 和 Web JSON 响应都带有稳定的顶层
`schema_version: "muse.selector.v1"`。这是结果/接口 envelope 的版本标识；新增字段保持向后兼容，已保存的 watch payload 重放时也保留该字段。嵌套的 `SearchSpec`、商品、挂牌和证据对象继续使用各自已有的对象版本字段。

实时 eBay Browse 查询可以用 `--offset` 读取指定的单页；`--limit` 仍是结果卡上限，来源请求至少保留连接器默认的 20 条以避免硬过滤过早截断。`offset` 必须是非负整数，命令只读取这一页，不会自动跟随 `next` 或继续分页：

```powershell
$env:EBAY_CLIENT_ID = "<official-app-id>"
$env:EBAY_CLIENT_SECRET = "<official-cert-id>"
python -m muse_selector `
  --query "香港 RTX 4070 显卡，预算 HKD 9000" `
  --limit 10 `
  --offset 40 `
  --format json
```

返回 JSON 的 `source_metadata.offset`、`limit`、`total`、`next` 和 `prev` 字段会标识实际收到的 Browse 页。fixture 模式也接受同样的参数，但 fixture 没有请求页语义时这些来源元数据保持其原始值。

比较 Artifact（保留来源顺序、实体标识、成本、证据覆盖率和风险）：

```powershell
python -m muse_selector `
  --query "香港预算 HKD 30000 以内的电脑" `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --format comparison
```

本地结果页（默认只读）：

```powershell
muse-selector-web `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --port 8765
```

也可以使用 `python -m muse_selector.web` 直接从源码启动同一个入口。

实时只读结果页可以显式选择 eBay 环境；进程退出后不会修改当前 PowerShell 会话的 `EBAY_ENVIRONMENT`：

```powershell
python -m muse_selector.web `
  --environment sandbox `
  --port 8765
```

然后打开 `http://127.0.0.1:8765/`。省略 `--fixture` 会进入实时只读路径；没有 eBay 官方凭据时页面显示 `source_unavailable`，不会偷偷回退到 fixture。
结果页只绑定 `127.0.0.1` 或 `::1`，不会监听局域网地址，避免其他租户读取本地结果。
成功结果页会在“来源元数据”折叠区显示来源响应的安全转义摘要（例如请求地址、返回总数和分页字段），便于核对结果来自哪一次只读响应；该区域不会执行或渲染来源返回的 HTML。
同一个本地服务还提供结构化只读端点，便于前端或桌面壳直接消费结果：

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8765/api/search?q=香港预算%20HKD%207000%20以内的迷你主机&limit=5"
```

端点复用相同的 SearchSpec、来源证据和过滤逻辑，只返回 JSON，不提供登录、购买或写操作；`limit` 非法时返回 `invalid_query`。可用非负整数 `offset` 读取指定的单个来源页（不会自动跟随 `next`），非法 `offset` 同样返回结构化 `invalid_query`，不会静默改成第 0 页：

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8765/api/search?q=香港预算%20HKD%207000%20以内的迷你主机&limit=5&offset=40"
```

本地服务还提供不联网的来源能力状态端点，用于判断 eBay 环境和凭据是否已经配置，以及国内来源是否仍处于人工入口模式：

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/capabilities"
```

返回只包含 `configured`、`partial` 或 `missing` 等凭据状态，并报告 eBay 当前环境、官方 API 主机和 OAuth 路径；不返回任何凭据值，也不会发起 eBay 或国内平台请求。

如果要让本地页面读取已经保存的观察任务快照，可额外绑定 SQLite 文件：

```powershell
python -m muse_selector.web `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --db "D:\muse\data\selector.sqlite3" `
  --port 8765

Invoke-RestMethod "http://127.0.0.1:8765/api/watch?watch_id=mini_pc_hk"
Invoke-RestMethod "http://127.0.0.1:8765/api/watches"
Invoke-RestMethod "http://127.0.0.1:8765/api/watch/changes?watch_id=mini_pc_hk&include_payload=1"
```

`/api/watch` 只读取单个 watch 元数据和最新已保存结果，`/api/watches` 返回全部 watch 元数据；两个端点都不会刷新来源、调用连接器或写入 SQLite。watch 元数据中的 `last_change_summary` 是最近一次刷新相对于上一个检查点的新增、移除、内容变化和状态变化摘要，即使观察进程已经退出也可以恢复。未绑定 `--db` 或 watch 不存在时返回结构化 `watch_unavailable` / `watch_not_found`。
`/api/watch/changes` 返回该 watch 的持久化检查点历史（按最新在前排序），每个事件带 `run_id`、`changed`、摘要和观测时间；追加 `include_payload=1` 可在同一个只读响应中带出可重放的 run payload。支持 `limit`（1–1000）和 `offset` 分页，服务重启后仍可继续读取，重复刷新同一个 deterministic run 不会制造重复历史行。
观察任务也可以保存 `price_max`、`stock_required`、`max_delivery_days` 三类本地阈值；刷新时产生 SQLite `watch_events`，相同 `watch_id + event_key` 只保留一次。事件只在条目进入阈值或离开后重新进入时产生，同一状态内的价格变化不会重复触发。来源不可用、策略阻断或需要补充条件时，失败快照会先保存，再把 watch 自动暂停，避免后台重复刷新；恢复仍需显式执行 `muse-watch --action resume`。CLI 使用 `muse-watch --action events` 读取，`muse-watch --action consume-events` 领取本地 outbox，Web 使用 `/api/watch/events` 读取；这些事件不发送外部通知，也不调用来源写接口。

运行离线回归：

```powershell
$env:PYTHONPATH = "D:\muse\src;D:\muse\tests"
python tests/regression_harness.py
python -m unittest discover -s tests -p "test_*.py" -v
```

国内结果层可以显式注入本地 CNY fixture 做离线回归；没有显式 connector 时，国内查询仍返回 `source_unavailable`，不会把 fixture 当成实时挂牌：

```powershell
$env:PYTHONPATH = "D:\muse\src"
@'
from muse_selector.connectors.local_fixture import LocalFixtureConnector
from muse_selector.pipeline import run_search

payload = run_search(
    "国内预算 CNY 8000 以内的二手迷你主机",
    connector=LocalFixtureConnector(r"D:\muse\tests\fixtures\domestic_cn_sample.json"),
)
print(payload["source"], payload["recommended"])
'@ | python -
```

SQLite 观察任务示例：

```powershell
@'
from muse_selector.persistence import SelectorStore

store = SelectorStore(r"D:\muse\data\selector.sqlite3")
watch_id = store.add_watch(
    "香港预算 HKD 7000 以内的迷你主机",
    r"D:\muse\tests\fixtures\ebay_hk_sample.json",
    interval_seconds=900,
    watch_id="mini_pc_hk",
)
print(store.refresh_watch(watch_id))
'@ | python -
```

观察任务只保存只读 run、结果卡和查询状态；没有凭据字段，也没有购买、出价、支付或账号操作。
每次刷新还会输出 `change_summary`，列出新增、移除或内容变化的 `listing_id`；相同结果重放时摘要为空，不会重复制造通知事件。

也可以直接运行一次观察刷新：

```powershell
$env:PYTHONPATH = "D:\muse\src"
python -m muse_selector.watch `
  --db "D:\muse\data\selector.sqlite3" `
  --watch-id "mini_pc_hk" `
  --query "香港预算 HKD 7000 以内的迷你主机" `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --once
```

去掉 `--once` 后按 `--interval-seconds` 持续刷新；按 `Ctrl+C` 停止。省略 `--fixture` 会走实时只读 API。
省略 `--watch-id` 时，程序会按“查询 + fixture”生成稳定 ID，重复启动同一命令会复用已有观察任务，不会重复创建记录。

观察任务也支持暂停、恢复、人工修改和无副作用重放；修改查询或来源后会清空该观察任务的最新 checkpoint，但旧 run 仍可按 `run_id` 重放：

```powershell
@'
from muse_selector.persistence import SelectorStore

store = SelectorStore(r"D:\muse\data\selector.sqlite3")
store.pause_watch("mini_pc_hk")
store.update_watch("mini_pc_hk", query="香港 RTX 4070 显卡，预算 HKD 9000", interval_seconds=600)
store.resume_watch("mini_pc_hk")
latest = store.refresh_watch("mini_pc_hk")
print(store.replay_run(latest["run_id"]))
'@ | python -
```

这些操作只修改本地观察状态或读取已保存结果，不会向来源平台发起写操作。`status` 和 Web 观察端点会保留并返回最近一次刷新摘要，便于在进程重启后判断观察任务是否发生变化。

同样可以直接使用 `muse-watch` 管理生命周期：

```powershell
muse-watch --db "D:\muse\data\selector.sqlite3" --action pause --watch-id "mini_pc_hk"
muse-watch --db "D:\muse\data\selector.sqlite3" --action resume --watch-id "mini_pc_hk"
muse-watch --db "D:\muse\data\selector.sqlite3" --action update --watch-id "mini_pc_hk" `
  --query "香港 RTX 4070 显卡，预算 HKD 9000" --interval-seconds 600
muse-watch --db "D:\muse\data\selector.sqlite3" --action update --watch-id "mini_pc_hk" --live
muse-watch --db "D:\muse\data\selector.sqlite3" --action replay --watch-id "mini_pc_hk"
muse-watch --db "D:\muse\data\selector.sqlite3" --action status --watch-id "mini_pc_hk"
muse-watch --db "D:\muse\data\selector.sqlite3" --action list
muse-watch --db "D:\muse\data\selector.sqlite3" --action changes --watch-id "mini_pc_hk" --include-payload
muse-watch --db "D:\muse\data\selector.sqlite3" --action consume-events --watch-id "mini_pc_hk"
```

观察任务会持久化 `environment`（`production` 或 `sandbox`）。创建或更新时显式传入 `--environment sandbox` 后，后续省略该参数的刷新仍会使用已保存的 Sandbox 目标；旧 SQLite 数据库迁移后默认使用 production。

这些 action 只读写本地 SQLite 状态；`replay`、`status`、`list`、`changes`、`events` 和 `consume-events` 不会调用连接器，`status` 会返回观察任务元数据和最新已保存结果，`list` 返回全部观察任务，`changes` 返回历史检查点并可用 `--include-payload` 导出可重放 payload，`events` 读取本地 outbox，`consume-events` 只在本地标记已领取事件，`update` 会保留旧 run 供重放。已有 fixture 观察任务可用 `--action update --live` 清除 fixture，原地切换到实时只读 API。
如果 `watch_id` 不存在，`refresh`（未提供查询时）、`status`、`changes`、`pause`、`resume`、`replay` 和 `update` 会返回带 `schema_version` 的只读 JSON 错误（例如 `status: "watch_not_found"`）并退出码 `2`，不会打印 traceback，也不会创建空查询观察任务。若 watch 元数据指向已丢失的 checkpoint，CLI 和 Web `/api/watch` 会返回 `watch_unavailable`，保留只读边界并提示重新刷新。

回归集覆盖预算、地区、必选规格、陈旧/冲突证据、缺失 URL、账号策略阻断、提示注入、SSRF 和重放稳定性。fixture 中的价格和库存是测试数据，不能当作当前市场报价。
回归产物 `examples/regression_result.json` 同时记录 `hard_constraint_violation_rate`；当前验收值必须为 `0.0`。
回归集的正例还带有明确的 `relevant_listing_ids` 标签，产物会报告基于 fixture 的
`Precision@10`、`Recall@20`、`NDCG@10` 和重放 `Top-k Jaccard` 基线；这些指标用于比较代码变更，不能当作实时市场质量或平台整体覆盖率。
本地反馈可通过 `tests/fixtures/feedback_events.json` 导入 SQLite，并用 `muse.selector.feedback.v1` 记录重放结果；回归脚本会检查反馈标签与推荐集合是否一致，不会访问外部平台。
同一回归产物还带有 `quality_report`：只使用来源明确提供的 GTIN、EPID、MPN、SKU 或品牌/型号做实体键，报告去重和 72 小时 TTL 统计；标题不会被用来猜测型号或实体身份。
W10 故障矩阵可独立运行 `python tests/fault_harness.py`，覆盖 OAuth/429/坏响应/token 脱敏、损坏 checkpoint、重复观察事件、SSRF 和提示注入；输出 `muse.selector.faults.v1`，不联网、不接触凭据。
W11 合成负载指标可运行 `python tests/metrics_harness.py`，输出 `muse.selector.metrics.v1`，记录 p50/p95、成功/失败率、硬约束违规率、checkpoint 重放稳定性和外部请求成本代理；fixture 模式的外部请求数必须为 0。
W11 跨市场 shadow 评测可运行 `python tests/shadow_harness.py`，输出 `muse.selector.shadow.v1`，同时重放香港兼容 fixture 和中国大陆 CNY 本地 fixture，验证结果顺序、硬约束违规率、只读状态和外部请求数。
逐项验收证据和唯一未验证的外部门见 [acceptance_matrix.md](acceptance_matrix.md)。
未完成的 W2–W12 执行顺序、并行边界、角色分工和 Go/No-Go 条件见 [remaining_execution_plan.md](remaining_execution_plan.md)。
启动、故障熔断、数据删除、事故响应和 Go/No-Go 操作见 [release_runbook.md](release_runbook.md)。
可用 `muse-release-check --root D:\\muse` 离线检查本地 artifact 和发布文档；当前会明确报告 `local_ready_external_gate_pending`，不会把 fixture 结果标记为真实生产通过。
拿到官方 keyset 后可追加 `muse-live-smoke --evidence-file examples/live_smoke_result.json ...` 保存脱敏 smoke 摘要；release check 只在摘要 schema、来源、只读标记、状态和环境都有效时记录 `real_smoke_recorded`，不会保存凭据或 token。
W8 只读浏览器 broker 目前是默认关闭的本地契约：只接受 eBay HK HTTPS allowlist，通过注入 adapter 读取 accessibility tree 并清理敏感字段；没有 click、type、JavaScript 或真实凭据路径。
关键字段证据覆盖率低于 95% 的来源记录会被标记为风险并排除，不会进入推荐。
查询未提供预算上限时，系统返回 `needs_clarification` 并要求补充地区与 `max_total_hkd`；只有明确写出“价格不限”等表达才会在无预算上限下继续筛选。
结果卡会同时输出 `cost_status` 和 `cost_basis`：税费或运费未知时显示“已知费用小计”，不会把未知税费伪装成完整到手价。
结果卡还会输出 `compatibility_matrix`：对每个 `required_specs` 给出 `confirmed`、`mismatch` 或 `unknown`，并保留对应 `evidence_ids` 和来源 URL；缺少字段证据时保持 `unknown`。
每张结果卡还会输出顶层 `evidence_ids`；它与卡片内 `evidence[].evidence_id` 一一对应，便于下游存储、回放和审计时直接定位证据，而无需解析证据正文。
查询中明确写出“X 天内送达”或 “delivery within X days”时，系统只使用 eBay `shippingOptions.maxEstimatedDeliveryDate` 相对来源观测时间计算配送上限；缺少预计日期的记录显示 `delivery_unknown` 并排除，不会猜测送达时间。结果卡会显示 `delivery_max_days`。
实时 eBay 响应中的 `itemEndDate` 会与本次抓取时间比较；已结束 listing 会保留 `itemEndDate` 证据并以 `listing_ended` 硬过滤。fixture 没有真实观测时钟，因此不会用本机当前时间改变离线回归结果。
结果卡也会显示来源明确提供的保修信息；没有保修字段时显示 `unknown`，不会根据标题或常识补写。
来源明确提供品牌、型号、MPN、GTIN 或 EPID 时，结果卡会保留实体标识和对应字段证据；缺失时保持 `unknown`。
eBay Browse API 的官方要求不允许合作方在客户端重新排序搜索结果，因此系统保留 eBay 返回的最佳匹配顺序，并在每张结果卡中显示 `source_rank`、`fit_score` 和拆解字段；预算、地区、库存、成色、必选规格和风险仍先经过硬约束过滤。

## 可选 eBay 只读 API

没有凭据或 eBay Buy API 生产访问批准时连接器会 fail-closed，只能使用 fixture。拿到官方 Production 应用凭据并完成 eBay 要求的生产访问流程后，仍然只调用 Browse API 的搜索接口：

```powershell
$env:EBAY_CLIENT_ID = "<official-app-id>"
$env:EBAY_CLIENT_SECRET = "<official-cert-id>"
$env:PYTHONPATH = "D:\muse\src"
python -m muse_selector --query "香港 RTX 4070 显卡，预算 HKD 9000" --format json
```

可以先用官方 Sandbox keyset 验证 OAuth、请求头和响应字段；Sandbox 结果只用于接口集成测试，不能当作当前市场报价：

```powershell
$env:EBAY_ENVIRONMENT = "sandbox"
$env:EBAY_CLIENT_ID = "<sandbox-app-id>"
$env:EBAY_CLIENT_SECRET = "<sandbox-cert-id>"
muse-live-smoke --environment sandbox --query "香港 RTX 4070 显卡，预算 HKD 9000"
```

生产和 Sandbox 可以分别保存凭据，连接器会按 `EBAY_ENVIRONMENT` 或命令行的显式环境选择对应 keyset：
`EBAY_PRODUCTION_CLIENT_ID` / `EBAY_PRODUCTION_CLIENT_SECRET` 与
`EBAY_SANDBOX_CLIENT_ID` / `EBAY_SANDBOX_CLIENT_SECRET`。如果选定环境没有专用变量，才回退到兼容用的
`EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`；一旦专用变量只设置了一半，系统保持 `partial`，不会与另一组凭据拼接。
`muse-doctor`、`muse-live-smoke` 和 `/api/capabilities` 会报告当前选用的变量名与 fallback 规则，但不会输出任何凭据值。

`SearchSpec.budget_min` 和 `budget_max` 会映射到 Browse API 的 `filter=price:[min..max]`，并同时发送
`priceCurrency=HKD`；只有上限或下限时，另一侧保持开放。连接器仍会在收到响应后执行本地预算硬过滤，避免运费、税费或
缺失价格造成边界误判。没有预算字段时不会添加价格过滤。

省略 `EBAY_ENVIRONMENT` 或设置为 `production` 时使用 `api.ebay.com`；`sandbox` 会严格锁定到 `api.sandbox.ebay.com`。

拿到官方凭据后可用一次性 smoke 命令验证实时只读链路。它只输出凭据状态、结果数量和证据时间摘要，不输出凭据或 token；没有凭据时返回 `source_unavailable` 并退出码 `2`：

```powershell
muse-live-smoke --query "香港 RTX 4070 显卡，预算 HKD 9000"
```

成功时 smoke 还会输出 eBay 返回的来源页元数据（`href`、`total`、`limit`、`offset` 和分页链接），用于确认真实响应页已被抓取；分页链接只保留官方 eBay Browse 搜索端点（生产或 Sandbox API 域名、固定搜索路径），其他值会被丢弃；它不会自动跟随 `next`。

实时连接器只对明确的瞬态 HTTP 状态 `429`、`500`、`502`、`503`、`504` 做有限重试；默认最多重试 2 次并使用短退避。可用 `EBAY_MAX_RETRIES` 和 `EBAY_RETRY_BACKOFF_SECONDS` 调整，认证、参数和其他 4xx 错误不会重试，也不会自动分页或跟随重定向。
如果响应提供合法的 `Retry-After`，连接器会优先采用并将等待时间限制在 30 秒；缺失或非法时回退到指数退避。
OAuth 和 Browse 响应体读取上限为 4,000,000 字节；超限时会 fail-closed 为 `source_unavailable`，不会继续解析超大响应。

如需立即停用实时 eBay 来源，可设置来源注册表中的 kill switch；它会在 OAuth 请求之前 fail-closed，fixture 离线模式不受影响：

```powershell
$env:MUSE_SOURCE_EBAY_BROWSE_HK_DISABLED = "1"
```

生产使用前需要再次核对 [eBay Buy API requirements](https://developer.ebay.com/api-docs/buy/buy-requirements.html)、API License Agreement、地区支持、缓存和展示规则。连接器不提供购物车、支付、出价或订单接口。

## 代码结构

- `scope_decision.md`：香港/HKD、电脑硬件、eBay HK 只读首版范围与降级决策。
- `src/muse_selector/contracts.py`：`SearchSpec`、`ProductModel`、`Listing`/`ListingInstance`、`Evidence`、`SourceCapability` 和 `PolicyRecord`。
- `src/muse_selector/category_registry.py`：手机、笔记本和显卡的品类属性注册表，声明类型、单位、硬条件和证据要求。
- `src/muse_selector/source_capabilities.py`：eBay、闲鱼、转转和本地 fixture 的来源能力注册表。
- `src/muse_selector/query_parser.py`：只解析用户明确写出的预算、品类和硬件规格，并保留解析置信度与待澄清字段。
- `src/muse_selector/connectors/ebay.py`：fixture/官方 Browse API 只读连接器。
- `src/muse_selector/connectors/zhuanzhuan.py`：转转官方 MCP 估价/回收入口只读连接器。
- `src/muse_selector/pipeline.py`：解析、来源查询、硬过滤和结果卡编排。
- `src/muse_selector/source_normalizer.py`：来源行、证据和品类属性的纯标准化。
- `src/muse_selector/ports.py`：来源连接器和观察存储的窄端口，便于替换适配器而不改领域规则。
- `src/muse_selector/application.py`：CLI、Web、诊断和观察任务共用的 `SearchApplication` 搜索用例入口。
- `src/muse_selector/watch_contracts.py`：`WatchSpec`、`RefreshJob`、`WatchEvent` 和 `AuditRecord`。
- `src/muse_selector/result_card.py`：JSON/Markdown 结果卡。
- `tests/fixtures/search_queries_v1.json`：20 条可解析的首版 SearchSpec 样例。
- `tests/`：契约、连接器、端到端结果卡和离线回归。
