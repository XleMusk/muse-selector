# Muse Selector 范围决策

状态：中国大陆二手电子产品与游戏账号只读发现是产品主线；香港 eBay 仅保留为历史兼容适配器和回归基线。

## 当前主线优先级

- 中国大陆（`CN`）和人民币（`CNY`）是后续产品主线。
- 未显式指定香港时，二手、闲置、used 等查询默认进入 CN/CNY 路由；显式香港查询才进入 HK/HKD 兼容路径。
- 国内电子产品查询通过来源能力注册和 fail-closed 路由运行；在获得官方挂牌搜索授权前，不把闲鱼或转转网页、Cookie 会话或私有接口当成搜索来源。
- 游戏账号查询属于独立领域：公开市场发现只返回官方人工入口和策略元数据；登录、密码、验证码、购买、出售、转移、代打、支付等动作保持阻断。

## 已冻结范围

- 主地区： 中国大陆（`CN`）。
- 主币种： 人民币（`CNY`）。
- 电子产品品类： 手机、笔记本、迷你主机、显卡、扩展坞和其他硬件配件。
- 游戏账号品类： 账号公开信息、游戏名、预算和成色等非敏感字段；不处理账号控制权。
- 香港兼容来源： eBay Browse API 的 `EBAY_HK` 市场，连接器标识为 `ebay.browse.hk.v1`。
- 允许的网络动作： 已登记官方/授权来源的只读请求；eBay OAuth/Browse 仅属于兼容适配器。
- 结果要求：来源 URL、来源标识、抓取/观测时间、字段级证据、成本状态、风险和只读状态必须可追溯。

## 明确排除

- 游戏账号登录、接收密码/Cookie/验证码、购买、转移、代打和支付。
- eBay 购物车、出价、订单、消息、收藏或任何其他写接口。
- 闲鱼和转转的非官方批量抓取、Cookie 复用、私有接口逆向和绕过风控。
- 游戏账号平台的登录、密码/Cookie/验证码读取、购买、出售、转移、代打、支付和私下交易撮合。
- 绕过登录、验证码、DRM、反爬、速率限制或平台访问控制。
- 未登记来源、非香港配送条件、SSRF/内网地址和未经证据支持的价格或规格推断。

## 数据与降级规则

- 没有完整官方凭据时，实时连接器 fail-closed；本地 fixture 只用于离线开发和回归，不能冒充实时库存或报价。
- 缺少关键证据、运费/税费不完整、字段冲突或陈旧时，结果显示未知/风险并排除出推荐。
- 查询明确要求配送时限时，只接受来源 `shippingOptions` 的预计最晚送达日期；日期缺失或无法计算时标记 `delivery_unknown` 并排除。
- eBay 返回的最佳匹配顺序保留在结果卡中；客户端不按价格重新排序。匹配分仅用于解释，不扩大来源权限。
- 观察任务只写本地 SQLite；run、结果卡和 watch checkpoint 在同一事务中提交，失败时整体回滚。
- 来源注册表的 `source_ebay_browse_hk` kill switch 在实时 OAuth 请求前生效；启用时连接器 fail-closed，离线 fixture 仍可用于回归。

## 国内来源状态

- `xianyu.partner.v1`：`partner_api_pending` / `link_only`。官方[合作方文档](https://open.goofish.com/doc/development/dev/server.html)需要 AppKey、OAuth、逐项权限和部分聚石塔部署；当前没有登记任意陌生挂牌的通用搜索权限。
- `zhuanzhuan.recommerce.mcp.v1`：官方[MCP](https://open.zhuanzhuan.com/mcp)估价辅助，能力为商品识别、回收估价和回收入口，不是挂牌搜索连接器；需要用户在官方控制台取得 Bearer Token。
- 国内查询在挂牌搜索来源未授权前返回 `source_unavailable`，绝不回退到 eBay 或非官方抓取。

游戏账号公开发现当前登记为人工入口：5173、淘手游和交易猫均只提供用户自行打开的官方入口卡；系统不抓取挂牌、不读取登录态，也不替用户完成交易动作。

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

当前验收需要 eBay Buy API 生产访问批准、正式协议和官方 Production 应用凭据，才能证明实时 API 成功响应；Production keyset 本身不等于生产访问权限。没有这些条件时不得伪造 live 成功。
