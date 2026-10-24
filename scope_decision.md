# Muse Selector v1 范围决策

状态：冻结，面向香港电脑/硬件只读筛选。

## 已冻结范围

- 地区：香港（`HK`）。
- 币种：港币（`HKD`）。
- 品类：电脑、笔记本、迷你主机、显卡、扩展坞和其他硬件配件。
- 首个来源：eBay Browse API 的 `EBAY_HK` 市场，连接器标识为 `ebay.browse.hk.v1`。
- 允许的网络动作：OAuth client-credentials 取应用访问令牌，以及 `item_summary/search` 的只读 `GET`。
- 结果要求：来源 URL、来源标识、抓取/观测时间、字段级证据、成本状态、风险和只读状态必须可追溯。

## 明确排除

- 游戏账号登录、接收密码/Cookie/验证码、购买、转移、代打和支付。
- eBay 购物车、出价、订单、消息、收藏或任何其他写接口。
- 绕过登录、验证码、DRM、反爬、速率限制或平台访问控制。
- 未登记来源、非香港配送条件、SSRF/内网地址和未经证据支持的价格或规格推断。

## 数据与降级规则

- 没有完整官方凭据时，实时连接器 fail-closed；本地 fixture 只用于离线开发和回归，不能冒充实时库存或报价。
- 缺少关键证据、运费/税费不完整、字段冲突或陈旧时，结果显示未知/风险并排除出推荐。
- eBay 返回的最佳匹配顺序保留在结果卡中；客户端不按价格重新排序。匹配分仅用于解释，不扩大来源权限。
- 观察任务只写本地 SQLite；run、结果卡和 watch checkpoint 在同一事务中提交，失败时整体回滚。

## 证据入口

- 来源登记：[data/source_registry.yaml](data/source_registry.yaml)
- SearchSpec 样例：[tests/fixtures/search_queries_v1.json](tests/fixtures/search_queries_v1.json)
- 回归查询：[tests/fixtures/queries.json](tests/fixtures/queries.json)
- 回归脚本：[tests/regression_harness.py](tests/regression_harness.py)
- 运行命令：

```powershell
$env:PYTHONPATH = "D:\\muse\\src;D:\\muse\\tests"
python -m unittest discover -s tests -p "test_*.py" -v
python tests/regression_harness.py
```

当前验收还需要真实 eBay 官方应用凭据才能证明实时 API 成功响应；没有凭据时不得伪造 live 成功。
