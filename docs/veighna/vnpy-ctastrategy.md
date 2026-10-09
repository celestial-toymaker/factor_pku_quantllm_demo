# vnpy_ctastrategy：策略接口与生命周期

固定提交：`7a8768de9784dda35a7b261a7ade1dbfbff50919`。

`CtaTemplate` 保存策略名、单个 vt_symbol、参数和变量。`inited` 表示初始化标志，`trading` 控制模板是否允许向引擎发单，`pos` 保存策略持仓。parameters 从配置更新，variables 用于状态展示与保存；它们不是交易所账户的完整账本。[^template]

| 阶段 | 源码入口 | 需要观察的行为 |
|---|---|---|
| 添加 | add_strategy | 检查名称和合约标识，实例化并建立合约到策略的映射 |
| 初始化 | init_strategy / _init_strategy | 提交初始化任务，调用 on_init，恢复变量，查询合约并订阅 |
| 启动 | start_strategy | 检查初始化标志，调用 on_start，设置 trading |
| 运行 | process_tick/order/trade_event | 分发行情，更新委托集合，去重成交并更新 pos |
| 停止 | stop_strategy | 调用 on_stop，关闭 trading，撤销策略委托并保存变量 |

上述顺序来自引擎实现。特别是 stop_strategy 会发起撤单，却不自动把已有持仓平掉；“停止策略”不能替代持仓核对。[^lifecycle]

`buy`、`sell`、`short`、`cover` 分别组合方向与开平类型，再交给模板 send_order。模板只有在 trading 为真时才转发；引擎进一步按合约价格和数量步长取整，并区分普通单、服务器停止单和本地停止单。一次策略调用可能返回多个订单号，调用方需要按实际返回集合管理订单。[^request][^route]

成交事件先查 vt_tradeid 去重集合，再更新策略 pos、执行 on_trade 并保存变量。这个去重集合是运行时状态；变量保存不能自动证明订单归属和去重记录在重启后完整。[^events]

异常处理还需要阅读调用者。`call_strategy_func` 捕获异常后将 inited 和 trading 置为假并记录日志；但本固定版本的 `_init_strategy` 和 `start_strategy` 在回调返回后仍继续执行，并在后面分别设置 inited 或 trading 为真。因此不能仅由该异常包装函数推断整个生命周期已经安全终止。[^errors][^lifecycle]

[策略应用与回测边界](strategy-applications.md)比较单标的、投组与价差应用，并定位回测撮合的价格和数量假设。[返回目录](index.md)

## 参考

[^template]: VeighNa, [CtaTemplate](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/template.py#L14)，初始化、参数、变量和回调接口。
[^lifecycle]: VeighNa, [策略添加、初始化、启动与停止](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/engine.py#L639)。
[^request]: VeighNa, [策略发单接口](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/template.py#L148)，buy/sell/short/cover、send_order。
[^route]: VeighNa, [CtaEngine.send_order](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/engine.py#L470)。
[^events]: VeighNa, [事件处理和成交去重](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/engine.py#L149)。
[^errors]: VeighNa, [call_strategy_func](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/engine.py#L618)。
