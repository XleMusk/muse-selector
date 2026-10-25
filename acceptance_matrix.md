# Muse Selector v1 验收矩阵

这份矩阵把目标拆成可复核的证据。fixture 和模拟 opener 只证明离线契约与实时适配逻辑，不冒充真实市场响应。

当前产品优先级已迁移到中国大陆电脑/硬件二手市场；香港 eBay 是已通过的只读基线。国内来源能力按官方授权状态逐个接入。

| 目标要求 | 当前证据 | 状态 |
| --- | --- | --- |
| 香港/HKD/电脑硬件 `SearchSpec` | `src/muse_selector/contracts.py`、`src/muse_selector/query_parser.py`、`tests/fixtures/search_queries_v1.json`、`tests/test_query_parser.py` | 已通过 |
| eBay HK 官方只读连接器 | `data/source_registry.yaml`、`src/muse_selector/connectors/ebay.py`、`tests/test_ebay_connector.py` | 连接器契约已通过；生产访问批准和凭据待完成 |
| OAuth/Browse 失败关闭与端点锁定 | `tests/test_ebay_live_adapter.py`、`tests/test_ebay_connector.py` | 已通过 |
| eBay Sandbox/Production 环境隔离 | `src/muse_selector/connectors/ebay.py`、`tests/test_ebay_live_adapter.py`、`tests/test_ebay_connector.py` | Sandbox 端点配对和环境标记已通过；Sandbox 不代表市场报价 |
| 实时字段适配、抓取时间和结束 listing 过滤 | `tests/test_ebay_live_adapter.py`、`tests/test_ebay_connector.py`、`src/muse_selector/filtering.py` | 适配逻辑已通过；已依据 `itemEndDate` 与 live 观测时间硬过滤；真实 API 待凭据 |
| 硬件实体标识（品牌/型号/MPN/GTIN/EPID） | `src/muse_selector/connectors/ebay.py`、`src/muse_selector/result_card.py`、`tests/test_ebay_live_adapter.py` | 已通过；只保留来源明确字段 |
| 来源、时间、字段证据、风险结果卡 | `src/muse_selector/result_card.py`、`src/muse_selector/web.py`、`tests/test_pipeline.py`、`tests/test_web.py` | 已通过 |
| 硬件兼容性矩阵 | `src/muse_selector/compatibility.py`、`src/muse_selector/result_card.py`、`tests/test_compatibility.py` | required_specs 逐项输出状态并保留证据引用；未知字段不推断 |
| 搜索/Smoke/Web 顶层结果契约版本 | `RESULT_SCHEMA_VERSION`、`tests/test_pipeline.py`、`tests/test_smoke.py`、`tests/test_web.py` | `muse.selector.v1` 已通过 |
| 来源顺序与单页召回 | `src/muse_selector/pipeline.py`、`tests/test_ebay_live_adapter.py` | 已通过；不自动跟随 `next` |
| CLI 和本地结果页 | `src/muse_selector/cli.py`、`src/muse_selector/web.py`、README 运行命令 | 已实际运行 |
| SQLite 持久化和观察任务 | `src/muse_selector/persistence.py`、`src/muse_selector/watch.py`、`tests/test_persistence.py`、`tests/test_watch.py` | 已实际运行；本地价格/库存/配送阈值事件可去重读取 |
| 单任务状态图与 checkpoint 重放 | `src/muse_selector/state_graph.py`、`tests/test_state_graph.py`、`.github/workflows/ci.yml` | 阶段状态、请求指纹和无连接器重放已通过 |
| Watch 变化检查点历史与本地重放读取 | `watch_changes` 表、`muse-watch --action changes`、`/api/watch/changes`、`tests/test_persistence.py`、`tests/test_web.py` | 已实际运行 |
| 离线回归、硬约束/排名和实体质量基线 | `tests/regression_harness.py`、`tests/fixtures/queries.json`、`examples/regression_result.json` | `ok=true`；`hard_constraint_violation_rate=0.0`；已输出 Precision@10、Recall@20、NDCG@10、Top-k Jaccard、显式实体键去重和 TTL 质量报告 |
| 凭据泄露、SSRF、分页元数据越界、越权来源、跨租户页面、重复副作用 | 连接器/管线/Web/SQLite 测试集；分页 `href`/`next`/`prev` 仅接受官方 eBay Browse 搜索端点；本地 Web 仅 loopback | 已通过 |
| 账号登录、购买、转移、代打、支付和平台控制绕过 | `src/muse_selector/query_parser.py`、`scope_decision.md` | 已排除并阻断 |
| GitHub 主线自动验证 | `.github/workflows/ci.yml` | 最新 CI 通过 |
| CN/CNY 国内市场 SearchSpec 与来源路由 | `src/muse_selector/contracts.py`、`src/muse_selector/query_parser.py`、`src/muse_selector/pipeline.py`、`tests/test_query_parser.py`、`tests/test_pipeline.py` | 契约和 fail-closed 路由已通过；官方挂牌搜索连接器待授权 |
| 转转官方 MCP 估价/回收入口适配 | `src/muse_selector/connectors/zhuanzhuan.py`、`tests/test_zhuanzhuan_connector.py`、`src/muse_selector/zhuanzhuan_smoke.py` | 官方 Streamable HTTP 工具调用、字段归一化、Token 缺失/权限错误 fail-closed 已通过；不作为挂牌搜索来源 |
| 闲鱼/转转官方能力登记 | `data/source_registry.yaml`、`scope_decision.md`、`src/muse_selector/link_only.py` | 闲鱼 link-only/pending；CN/CNY 查询会返回可人工打开的官方入口卡；转转官方 MCP 估价/回收入口适配已完成 |

## 当前外部验收门

香港 eBay 基线需要 eBay Buy API 生产访问批准/协议以及官方 Production 应用凭据 `EBAY_CLIENT_ID` 和 `EBAY_CLIENT_SECRET` 才能运行真实一次性 smoke：

```powershell
$env:EBAY_CLIENT_ID = "<official-app-id>"
$env:EBAY_CLIENT_SECRET = "<official-cert-id>"
muse-live-smoke --query "香港 RTX 4070 显卡，预算 HKD 9000"
```

没有凭据或生产访问尚未开通时，预期结果是 `source_unavailable`、`read_only=true`、退出码 `2`。在生产批准、凭据和真实响应都验证前，不把 fixture 或模拟 opener 宣称为实时市场成功。

中国大陆挂牌搜索还需要闲鱼或其他国内平台提供明确的官方搜索权限/合作方接口。转转当前官方能力仍是估价和回收入口，不能作为挂牌搜索验收门；取得 Token 后可运行 `muse-zhuanzhuan-smoke` 验证估价辅助链路。
