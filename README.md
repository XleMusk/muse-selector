# Muse Selector MVP

香港电脑/硬件的只读筛选原型。首个来源是 eBay Browse API 的 `EBAY_HK`
`item_summary/search` 适配层；本地开发和回归默认使用 fixture，不联网、不接收用户凭据、没有写操作接口。

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

本地结果页（默认只读）：

```powershell
python -m muse_selector.web `
  --fixture "D:\muse\tests\fixtures\ebay_hk_sample.json" `
  --port 8765
```

然后打开 `http://127.0.0.1:8765/`。省略 `--fixture` 会进入实时只读路径；没有 eBay 官方凭据时页面显示 `source_unavailable`，不会偷偷回退到 fixture。
结果页只绑定 `127.0.0.1` 或 `::1`，不会监听局域网地址，避免其他租户读取本地结果。

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
muse-watch --db "D:\muse\data\selector.sqlite3" --action replay --watch-id "mini_pc_hk"
```

这些 action 只读写本地 SQLite 状态；`replay` 不会调用连接器，`update` 会保留旧 run 供重放。

回归集覆盖预算、地区、必选规格、陈旧/冲突证据、缺失 URL、账号策略阻断、提示注入、SSRF 和重放稳定性。fixture 中的价格和库存是测试数据，不能当作当前市场报价。
回归产物 `examples/regression_result.json` 同时记录 `hard_constraint_violation_rate`；当前验收值必须为 `0.0`。
关键字段证据覆盖率低于 95% 的来源记录会被标记为风险并排除，不会进入推荐。
查询未提供预算上限时，系统返回 `needs_clarification` 并要求补充地区与 `max_total_hkd`；只有明确写出“价格不限”等表达才会在无预算上限下继续筛选。
结果卡会同时输出 `cost_status` 和 `cost_basis`：税费或运费未知时显示“已知费用小计”，不会把未知税费伪装成完整到手价。
查询中明确写出“X 天内送达”或 “delivery within X days”时，系统只使用 eBay `shippingOptions.maxEstimatedDeliveryDate` 相对来源观测时间计算配送上限；缺少预计日期的记录显示 `delivery_unknown` 并排除，不会猜测送达时间。结果卡会显示 `delivery_max_days`。
结果卡也会显示来源明确提供的保修信息；没有保修字段时显示 `unknown`，不会根据标题或常识补写。
eBay Browse API 的官方要求不允许合作方在客户端重新排序搜索结果，因此系统保留 eBay 返回的最佳匹配顺序，并在每张结果卡中显示 `source_rank`、`fit_score` 和拆解字段；预算、地区、库存、成色、必选规格和风险仍先经过硬约束过滤。

## 可选 eBay 只读 API

没有凭据时连接器会 fail-closed，只能使用 fixture。拿到 eBay 官方应用凭据后，仍然只调用 Browse API 的搜索接口：

```powershell
$env:EBAY_CLIENT_ID = "<official-app-id>"
$env:EBAY_CLIENT_SECRET = "<official-cert-id>"
$env:PYTHONPATH = "D:\muse\src"
python -m muse_selector --query "香港 RTX 4070 显卡，预算 HKD 9000" --format json
```

拿到官方凭据后可用一次性 smoke 命令验证实时只读链路。它只输出凭据状态、结果数量和证据时间摘要，不输出凭据或 token；没有凭据时返回 `source_unavailable` 并退出码 `2`：

```powershell
muse-live-smoke --query "香港 RTX 4070 显卡，预算 HKD 9000"
```

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
- `src/muse_selector/pipeline.py`：解析、来源查询、规范化、硬过滤和结果卡。
- `src/muse_selector/result_card.py`：JSON/Markdown 结果卡。
- `tests/fixtures/search_queries_v1.json`：20 条可解析的首版 SearchSpec 样例。
- `tests/`：契约、连接器、端到端结果卡和离线回归。
