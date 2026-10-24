# Muse Selector v1 验收矩阵

这份矩阵把目标拆成可复核的证据。fixture 和模拟 opener 只证明离线契约与实时适配逻辑，不冒充真实市场响应。

| 目标要求 | 当前证据 | 状态 |
| --- | --- | --- |
| 香港/HKD/电脑硬件 `SearchSpec` | `src/muse_selector/contracts.py`、`src/muse_selector/query_parser.py`、`tests/fixtures/search_queries_v1.json`、`tests/test_query_parser.py` | 已通过 |
| eBay HK 官方只读连接器 | `data/source_registry.yaml`、`src/muse_selector/connectors/ebay.py`、`tests/test_ebay_connector.py` | 已通过 |
| OAuth/Browse 失败关闭与端点锁定 | `tests/test_ebay_live_adapter.py`、`tests/test_ebay_connector.py` | 已通过 |
| 实时字段适配、抓取时间和结束 listing 过滤 | `tests/test_ebay_live_adapter.py`、`tests/test_ebay_connector.py`、`src/muse_selector/filtering.py` | 适配逻辑已通过；已依据 `itemEndDate` 与 live 观测时间硬过滤；真实 API 待凭据 |
| 来源、时间、字段证据、风险结果卡 | `src/muse_selector/result_card.py`、`src/muse_selector/web.py`、`tests/test_pipeline.py`、`tests/test_web.py` | 已通过 |
| 来源顺序与单页召回 | `src/muse_selector/pipeline.py`、`tests/test_ebay_live_adapter.py` | 已通过；不自动跟随 `next` |
| CLI 和本地结果页 | `src/muse_selector/cli.py`、`src/muse_selector/web.py`、README 运行命令 | 已实际运行 |
| SQLite 持久化和观察任务 | `src/muse_selector/persistence.py`、`src/muse_selector/watch.py`、`tests/test_persistence.py`、`tests/test_watch.py` | 已实际运行 |
| 离线回归和硬约束 | `tests/regression_harness.py`、`examples/regression_result.json` | `ok=true`；`hard_constraint_violation_rate=0.0` |
| 凭据泄露、SSRF、越权来源、跨租户页面、重复副作用 | 连接器/管线/Web/SQLite 测试集；本地 Web 仅 loopback | 已通过 |
| 账号登录、购买、转移、代打、支付和平台控制绕过 | `src/muse_selector/query_parser.py`、`scope_decision.md` | 已排除并阻断 |
| GitHub 主线自动验证 | `.github/workflows/ci.yml` | 最新 CI 通过 |

## 当前唯一外部验收门

需要官方 eBay 应用凭据 `EBAY_CLIENT_ID` 和 `EBAY_CLIENT_SECRET` 才能运行真实一次性 smoke：

```powershell
$env:EBAY_CLIENT_ID = "<official-app-id>"
$env:EBAY_CLIENT_SECRET = "<official-cert-id>"
muse-live-smoke --query "香港 RTX 4070 显卡，预算 HKD 9000"
```

没有凭据时，预期结果是 `source_unavailable`、`read_only=true`、退出码 `2`。在凭据注入前，不把 fixture 或模拟 opener 宣称为实时市场成功。
