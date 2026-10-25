# Muse Selector MVP

中国大陆电脑/硬件二手市场是当前产品主线；香港 eBay 的 `EBAY_HK`
`item_summary/search` 适配层作为已验证的只读基线保留。本地开发和回归默认使用 fixture，不联网、不接收用户凭据、没有写操作接口。

## 中国大陆二手市场状态

当前 CN/CNY 查询已经进入 SearchSpec 和安全路由，但会在没有官方挂牌搜索授权时返回 `source_unavailable`。闲鱼公开合作方能力需要入驻、OAuth、逐项权限申请和相应部署条件；转转公开官方 MCP 当前提供商品识别、回收估价和回收入口，不提供通用挂牌搜索。

无官方挂牌搜索权限时，结果 JSON/Markdown 仍会给出 `link_only` 人工入口卡：包含官方平台入口、原始手动查询和只读说明。用户可以点击官方入口并在平台内自行搜索；系统不会抓取、排序、读取登录态或执行写操作。这是人工接管路径，不是 API 搜索结果。

因此，国内主线的第一步是获得官方搜索能力或合作方授权；系统不会使用 Cookie、私有接口、逆向签名或网页批量抓取来填补这个缺口。详见 [scope_decision.md](scope_decision.md) 和 [acceptance_matrix.md](acceptance_matrix.md)。

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

如果要安装命令入口，可先执行一次：

```powershell
python -m pip install --no-deps -e D:\muse
muse-selector --help
```

也可以不安装，使用下面的 `PYTHONPATH` 方式直接运行源码。

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

比较 Artifact（保留来源顺序、实体标识、成本、证据覆盖率和风险）：

```powershell
python -m muse_selector `
  --query "香港预算 HKD 30000 以内的电脑" `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --format comparison
```

本地结果页（默认只读）：

```powershell
python -m muse_selector.web `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --port 8765
```

实时只读结果页可以显式选择 eBay 环境；进程退出后不会修改当前 PowerShell 会话的 `EBAY_ENVIRONMENT`：

```powershell
python -m muse_selector.web `
  --environment sandbox `
  --port 8765
```

然后打开 `http://127.0.0.1:8765/`。省略 `--fixture` 会进入实时只读路径；没有 eBay 官方凭据时页面显示 `source_unavailable`，不会偷偷回退到 fixture。
结果页只绑定 `127.0.0.1` 或 `::1`，不会监听局域网地址，避免其他租户读取本地结果。
同一个本地服务还提供结构化只读端点，便于前端或桌面壳直接消费结果：

```powershell
Invoke-RestMethod `
  "http://127.0.0.1:8765/api/search?q=香港预算%20HKD%207000%20以内的迷你主机&limit=5"
```

端点复用相同的 SearchSpec、来源证据和过滤逻辑，只返回 JSON，不提供登录、购买或写操作；`limit` 非法时返回 `invalid_query`。

本地服务还提供不联网的来源能力状态端点，用于判断 eBay 环境和凭据是否已经配置，以及国内来源是否仍处于人工入口模式：

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/capabilities"
```

返回只包含 `configured`、`partial` 或 `missing` 等凭据状态，不返回任何凭据值，也不会发起 eBay 或国内平台请求。

如果要让本地页面读取已经保存的观察任务快照，可额外绑定 SQLite 文件：

```powershell
python -m muse_selector.web `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --db "D:\muse\data\selector.sqlite3" `
  --port 8765

Invoke-RestMethod "http://127.0.0.1:8765/api/watch?watch_id=mini_pc_hk"
```

`/api/watch` 只读取 watch 元数据和最新已保存结果，不会刷新来源、不调用连接器，也不会写入 SQLite；未绑定 `--db` 或 watch 不存在时返回结构化 `watch_unavailable` / `watch_not_found`。

运行离线回归：

```powershell
$env:PYTHONPATH = "D:\muse\src;D:\muse\tests"
python tests/regression_harness.py
python -m unittest discover -s tests -p "test_*.py" -v
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

这些操作只修改本地观察状态或读取已保存结果，不会向来源平台发起写操作。

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
```

这些 action 只读写本地 SQLite 状态；`replay`、`status` 和 `list` 不会调用连接器，`status` 会返回观察任务元数据和最新已保存结果，`list` 返回全部观察任务，`update` 会保留旧 run 供重放。已有 fixture 观察任务可用 `--action update --live` 清除 fixture，原地切换到实时只读 API。

回归集覆盖预算、地区、必选规格、陈旧/冲突证据、缺失 URL、账号策略阻断、提示注入、SSRF 和重放稳定性。fixture 中的价格和库存是测试数据，不能当作当前市场报价。
回归产物 `examples/regression_result.json` 同时记录 `hard_constraint_violation_rate`；当前验收值必须为 `0.0`。
逐项验收证据和唯一未验证的外部门见 [acceptance_matrix.md](acceptance_matrix.md)。
关键字段证据覆盖率低于 95% 的来源记录会被标记为风险并排除，不会进入推荐。
查询未提供预算上限时，系统返回 `needs_clarification` 并要求补充地区与 `max_total_hkd`；只有明确写出“价格不限”等表达才会在无预算上限下继续筛选。
结果卡会同时输出 `cost_status` 和 `cost_basis`：税费或运费未知时显示“已知费用小计”，不会把未知税费伪装成完整到手价。
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

省略 `EBAY_ENVIRONMENT` 或设置为 `production` 时使用 `api.ebay.com`；`sandbox` 会严格锁定到 `api.sandbox.ebay.com`。

拿到官方凭据后可用一次性 smoke 命令验证实时只读链路。它只输出凭据状态、结果数量和证据时间摘要，不输出凭据或 token；没有凭据时返回 `source_unavailable` 并退出码 `2`：

```powershell
muse-live-smoke --query "香港 RTX 4070 显卡，预算 HKD 9000"
```

成功时 smoke 还会输出 eBay 返回的来源页元数据（`href`、`total`、`limit`、`offset` 和分页链接），用于确认真实响应页已被抓取；它不会自动跟随 `next`。

实时连接器只对明确的瞬态 HTTP 状态 `429`、`500`、`502`、`503`、`504` 做有限重试；默认最多重试 2 次并使用短退避。可用 `EBAY_MAX_RETRIES` 和 `EBAY_RETRY_BACKOFF_SECONDS` 调整，认证、参数和其他 4xx 错误不会重试，也不会自动分页或跟随重定向。
如果响应提供合法的 `Retry-After`，连接器会优先采用并将等待时间限制在 30 秒；缺失或非法时回退到指数退避。

如需立即停用实时 eBay 来源，可设置来源注册表中的 kill switch；它会在 OAuth 请求之前 fail-closed，fixture 离线模式不受影响：

```powershell
$env:MUSE_SOURCE_EBAY_BROWSE_HK_DISABLED = "1"
```

生产使用前需要再次核对 [eBay Buy API requirements](https://developer.ebay.com/api-docs/buy/buy-requirements.html)、API License Agreement、地区支持、缓存和展示规则。连接器不提供购物车、支付、出价或订单接口。

## 代码结构

- `scope_decision.md`：香港/HKD、电脑硬件、eBay HK 只读首版范围与降级决策。
- `src/muse_selector/contracts.py`：`SearchSpec`、`Listing`、`Product`、`Evidence`、`PolicyRecord`。
- `src/muse_selector/query_parser.py`：只解析用户明确写出的预算和硬件规格。
- `src/muse_selector/connectors/ebay.py`：fixture/官方 Browse API 只读连接器。
- `src/muse_selector/connectors/zhuanzhuan.py`：转转官方 MCP 估价/回收入口只读连接器。
- `src/muse_selector/pipeline.py`：解析、来源查询、规范化、硬过滤和结果卡。
- `src/muse_selector/result_card.py`：JSON/Markdown 结果卡。
- `tests/fixtures/search_queries_v1.json`：20 条可解析的首版 SearchSpec 样例。
- `tests/`：契约、连接器、端到端结果卡和离线回归。
