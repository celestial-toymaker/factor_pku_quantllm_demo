# vnpy：平台骨架与标准数据

固定提交：`c6e231caf32b7fc97e6459817fff66458cf7e7c4`。

`MainEngine` 组织网关和功能引擎，`EventEngine` 负责事件分发。创建 MainEngine 时会启动事件引擎、建立组件字典、切换到 TRADER_DIR 并初始化功能引擎；`add_gateway` 根据网关类创建实例并登记支持的交易所。因此构造 MainEngine 本身已有线程和工作目录方面的副作用，阅读单个接口时要把初始化过程一并考虑。[^main]

标准对象把不同柜台的字段转换为策略可以统一使用的语义：[^objects]

| 对象 | 核心含义 | 阅读时需要区分的边界 |
|---|---|---|
| TickData / BarData | 时点行情 / 区间行情 | 行情时间与处理时间；区间结束后才完整的字段 |
| ContractData | 合约及交易约束 | 价格步长、数量步长与市场标识 |
| OrderRequest / OrderData | 发单请求 / 委托回报 | 请求意图与柜台确认的状态 |
| TradeData | 单次成交回报 | 委托数量与实际成交数量 |
| PositionData / AccountData | 持仓 / 资金快照 | 缓存值与查询完成后的柜台状态 |

`vt_symbol`、`vt_orderid`、`vt_tradeid` 等字段统一标识格式。它们帮助跨模块关联对象；是否能用于重启后的归属判断，还取决于底层标识的命名空间和应用是否保留了持久记录。[^objects]

`BaseGateway.on_tick` 把 Tick 放入普通事件和合约专属事件。EventEngine 从队列取出事件后，先执行该类型的处理器，再执行通用处理器；处理器在同一分发线程内依次运行。定时线程负责把定时事件放入队列，而不是替每个策略创建一个独立线程。[^gateway][^event]

OMS 保存最新对象并维护活动委托集合。订单、成交和持仓更新还会交给 OffsetConverter，使开平转换使用可用持仓与冻结持仓。缓存提供查询便利，但进程重启后仍需要从外部状态重建；初始空字典不等于已确认空仓。[^oms]

[行情链](events-and-data.md)说明标准对象的形成与分发，[委托链](orders-and-reconciliation.md)说明请求如何沿网关返回柜台。[返回目录](index.md)

## 参考

[^main]: VeighNa, [MainEngine 初始化与组件注册](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/engine.py#L92)，`__init__`、`add_engine`、`add_gateway`。
[^objects]: VeighNa, [标准数据对象](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/object.py#L30)。
[^gateway]: VeighNa, [BaseGateway.on_event/on_tick](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/gateway.py#L92)。
[^event]: VeighNa, [EventEngine](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/event/engine.py#L35)，队列、处理线程和定时线程。
[^oms]: VeighNa, [OmsEngine 事件处理](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/engine.py#L420)，订单、成交、持仓与开平转换器。
