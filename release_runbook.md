# Muse Selector W12 Runbook

## 发布边界

当前默认发布形态是香港电脑/硬件的只读筛选。允许的来源是 eBay HK 官方 Browse API 适配层和本地 fixture；国内来源保持 link-only 或官方转转估价辅助。系统不执行登录、购买、支付、出价、账号转移、发信或平台写操作。

生产 eBay 结果只有在官方 Buy API 访问批准、对应 keyset、真实 OAuth/Browse smoke 和字段证据核对全部通过后才可以标记为 live verified。Sandbox 只证明接口集成，不证明市场报价。

拿到官方 keyset 后，smoke 可以把脱敏证据写入本地文件：

```powershell
muse-live-smoke --environment sandbox --query "香港 RTX 4070 显卡，预算 HKD 9000" --evidence-file D:\muse\examples\live_smoke_result.json
muse-release-check --root D:\muse
```

证据文件只包含 smoke 摘要、来源元数据和观测时间，不包含 credential、token 或 secret。真实生产批准仍需独立记录，不能由存在凭据变量推断。

## 启动和健康检查

```powershell
Set-Location D:\muse
python -m pip install --no-deps -e .
muse-doctor --fixture D:\muse\tests\fixtures\ebay_hk_sample.json
muse-selector-web --fixture D:\muse\tests\fixtures\ebay_hk_sample.json --port 8765
```

本地结果页只绑定 loopback。检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8765/healthz
Invoke-RestMethod "http://127.0.0.1:8765/api/search?q=香港预算%20HKD%207000%20以内的迷你主机&limit=5"
Invoke-RestMethod http://127.0.0.1:8765/api/capabilities
```

观察任务读取不刷新来源：

```powershell
muse-watch --db D:\muse\data\selector.sqlite3 --action status --watch-id mini_pc_hk
muse-watch --db D:\muse\data\selector.sqlite3 --action changes --watch-id mini_pc_hk --include-payload
muse-watch --db D:\muse\data\selector.sqlite3 --action events --watch-id mini_pc_hk
```

## 质量门命令

```powershell
python -m unittest discover -s tests -p "test_*.py" -q
python tests/regression_harness.py
python tests/fault_harness.py
python tests/metrics_harness.py
git diff --check
```

必须满足：`hard_constraint_violation_rate=0.0`、fault matrix `ok=true`、metrics `ok=true`、`read_only=true`、fixture 模式外部请求成本代理为 0、checkpoint 重放无差异。GitHub CI 必须为绿色。

## 来源故障和熔断

- OAuth、429、5xx、超时或坏 JSON：保留 `source_unavailable`，不把错误响应转成推荐，不执行写动作。
- 真实 eBay 需要立即停止时设置 `MUSE_SOURCE_EBAY_BROWSE_HK_DISABLED=1`，重启进程后确认来源显示 disabled。
- 凭据疑似泄露时停止 live smoke，撤销/轮换官方 keyset；不要把凭据写入日志、fixture、数据库或 Git。
- 生产字段与 fixture 不一致时停止来源扩展，保留原始字段证据和 `unknown`，先修适配测试。

## 数据删除和保留

SQLite 只保存本地 read-only run、结果卡、watch 元数据、变化历史和本地阈值事件，不保存 eBay 凭据或 token。删除前停止 Web 和 watch 进程；需要保留证据时先复制脱敏回归产物，再删除本地数据库：

```powershell
Remove-Item -LiteralPath D:\muse\data\selector.sqlite3 -Force
```

删除后用空数据库运行 `muse-watch --action list`，确认没有旧 watch、run 或 event。外部平台缓存和平台数据不由本程序删除。

## 事故响应和回滚

1. 停止本地 Web/watch 进程，记录时间、命令、schema 版本和脱敏错误状态。
2. 若涉及凭据、SSRF、越权出口、未审批写或重复副作用，立即启用 eBay kill switch，保持来源只读。
3. 运行 `python tests/fault_harness.py` 和回归集，确认故障可复现且没有秘密出现在输出。
4. 回滚到最近一个绿色主线提交；恢复前先核对 SQLite checkpoint 和 `watch_events` 是否存在损坏指针。
5. 修复后重新运行全量测试、回归、fault harness、metrics harness 和 CI，再恢复有限只读运行。

## 当前 Go/No-Go

当前允许：fixture 离线演示、loopback Web、SQLite 观察任务、只读结果卡、兼容性矩阵、故障和合成负载评测。

当前 No-Go：未获得官方 keyset 和生产访问批准前的 live verified 声明；任何登录、购买、支付、账号转移、发信、平台写操作；W8 浏览器 broker 的真实凭据和未隔离出口。

生产 Go 条件：真实 eBay Sandbox/Production smoke 均能追溯官方 host 和字段；证据覆盖率至少 95%；硬约束违规率为 0；观察事件和 checkpoint 幂等；SSRF、提示注入、token 泄露、跨租户读取和未审批写为 0；p95、失败率、纠错率、成本和回滚均有可复现基线。
