# 策略应用与回测边界

`CtaEngine.process_tick_event` 把 Tick 交给对应且已初始化的策略；`process_order_event` 更新策略活动委托集合；`process_trade_event` 先用成交号集合去重，再更新持仓并调用 `on_trade`。策略变量落盘与完整订单归属、成交去重日志的持久化不是同一件事。重启后不能仅依赖内存集合恢复交易。[^events]

| 应用 | 主要状态与约束 | 本次学习范围 |
|---|---|---|
| 单标的时序策略 | 一个合约的信号、委托、成交、持仓和生命周期 | CTA 模板中的单个 vt_symbol、pos 及回调接口 |
| 多标的投组策略 | 每个合约独立状态，加上总资金、风险预算、行情不同步和目标仓位协调 | 从单标的模板边界推导的架构比较 |
| 价差套利应用 | 每条腿的实际成交、未对冲暴露、数量比和第二腿失败处理 | 从异步订单与成交路径推导的架构比较 |

后两行是由多合约状态约束得到的设计分析；源码证据限定在本 Wiki 列出的三个模块。单标的模板中的一个 pos 不能完整表达多条腿的实际成交状态，组合目标也不保证多个委托同时成交。

官方 CTA 回测器在 bar 模式下以 low/high 判断限价单是否穿越，并用开盘价改善成交价格；tick 模式用买一卖一。匹配后直接把 `order.traded` 设为整个 `order.volume`。这个撮合函数没有实现盘口排队或逐笔部分成交容量。相同策略接口不意味着回测成交与柜台执行等价。[^matching]

同一策略接口可用于不同执行环境，但结果依赖环境采用的撮合和记账规则。阅读回测结果时，应回到撮合函数检查时点、可成交价格、成交数量和费用，而不能只比较策略名称。

[返回目录](index.md) · [委托、成交与对账](orders-and-reconciliation.md)

## 参考

[^events]: VeighNa, [CtaEngine 事件处理](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/engine.py#L149)，process_tick_event、process_order_event、process_trade_event。
[^matching]: VeighNa, [BacktestingEngine.cross_limit_order](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/backtesting.py#L688)。
