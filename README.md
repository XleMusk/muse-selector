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

回归集覆盖预算、地区、必选规格、陈旧/冲突证据、缺失 URL、账号策略阻断、提示注入、SSRF 和重放稳定性。fixture 中的价格和库存是测试数据，不能当作当前市场报价。
回归产物 `examples/regression_result.json` 同时记录 `hard_constraint_violation_rate`；当前验收值必须为 `0.0`。
查询未提供预算上限时，系统返回 `needs_clarification` 并要求补充地区与 `max_total_hkd`；只有明确写出“价格不限”等表达才会在无预算上限下继续筛选。

## 可选 eBay 只读 API

没有凭据时连接器会 fail-closed，只能使用 fixture。拿到 eBay 官方应用凭据后，仍然只调用 Browse API 的搜索接口：

```powershell
$env:EBAY_CLIENT_ID = "<official-app-id>"
$env:EBAY_CLIENT_SECRET = "<official-cert-id>"
$env:PYTHONPATH = "D:\muse\src"
python -m muse_selector --query "香港 RTX 4070 显卡，预算 HKD 9000" --format json
```

生产使用前需要再次核对 eBay Buy API requirements、API License Agreement、地区支持、缓存和展示规则。连接器不提供购物车、支付、出价或订单接口。

## 代码结构

- `src/muse_selector/contracts.py`：`SearchSpec`、`Listing`、`Product`、`Evidence`、`PolicyRecord`。
- `src/muse_selector/query_parser.py`：只解析用户明确写出的预算和硬件规格。
- `src/muse_selector/connectors/ebay.py`：fixture/官方 Browse API 只读连接器。
- `src/muse_selector/pipeline.py`：解析、来源查询、规范化、硬过滤和结果卡。
- `src/muse_selector/result_card.py`：JSON/Markdown 结果卡。
- `tests/`：契约、连接器、端到端结果卡和离线回归。
