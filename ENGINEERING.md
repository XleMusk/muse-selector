# Muse 工程约定

这份文件是仓库内的执行标准。它把 `Muse_代码工程化重构与高手风格学习方案_20261025.pdf` 中适用于本项目的建议落成可执行规则；PDF 本身是参考方案，不替代具体任务要求。

## 结构和依赖

项目保持模块化单体。依赖方向固定为 `CLI/Web -> 应用用例 -> 领域与端口 -> 适配器`。`SearchSpec`、`Listing`、`Evidence`、过滤排序、兼容性判断和监控事件属于领域规则；eBay、HTTP、SQLite 和用户链接属于适配器或基础设施。领域模块不得导入 Click、Web 服务器、SQLite 客户端或平台 SDK。外部来源通过 `ports.py` 的窄接口进入搜索管线，连接器替换不应改动过滤、兼容性和结果卡规则。

外部 JSON 只能停留在连接器边界，进入搜索管线前必须标准化成领域对象。缺失值保持 `unknown` 或 `None`，不通过默认值伪造事实。新增来源优先增加适配器和契约测试，新增品类优先增加品类规则；游戏账号保持独立领域，不塞进电子产品商品模型。

来源能力统一使用 `SourceCapability` 描述，访问模式只能是 `official_api`、`authorized_partner`、`user_link` 或 `local_fixture`。品类字段统一登记在 `category_registry.py`；手机、笔记本和显卡的专属属性进入 `category_attributes`，未知字段不能自动成为硬条件。

## 修改方式

一次修改只解决一个可观察的问题。行为保持重构、业务修复和新功能分开提交。先读调用方和相关测试，写清楚要保持的契约，再做最小改动。纯计算与网络、时间、数据库 I/O 分开；时间和外部依赖通过参数或端口进入。公共函数的名字要说明动作，例如 `parse`、`normalize`、`validate`、`load`、`save`、`refresh`，避免无语义的 `process`、`handle` 和 `manage`。

错误必须能区分无结果、来源不可用、输入格式错误、权限不足和内部故障。不要使用宽泛 `except Exception`、静默降级、无限重试、隐式网络访问或把敏感信息写入日志。URL、来源、证据和只读边界的规则只保留一个实现入口。

## 验证和提交

修改后先运行受影响的定向测试，再运行完整测试：

```powershell
python -m unittest discover -s tests -p 'test_*.py' -q
python tests/regression_harness.py
```

连接器或存储变更需要补相应的 fake/stub 行为测试；领域规则优先写快速单测；CLI 和 Web 只保留少量端到端测试。提交说明要包含改变的问题、是否改变公共行为、运行过的命令和已知未验证项。新增依赖必须说明用途、版本、许可证和为什么不能用现有依赖。
