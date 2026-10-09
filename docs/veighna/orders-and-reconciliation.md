# 委托、成交与对账

策略发单沿普通方法调用向下传递：`CtaTemplate.buy/sell/short/cover` → `CtaEngine.send_order` → 合约价格/数量取整与开平转换 → `MainEngine.send_order` → 网关 → TD API。回报经事件总线向上传递，因此系统并非所有调用都只走事件总线。`buy` 是买开，`sell` 是卖平，`short` 是卖开，`cover` 是买平。[^template][^send][^main]

`CtpTdApi.onRtnOrder` 用 FrontID、SessionID 和 OrderRef 构造本地订单标识，并把交易所 OrderSysID 映射到它；成交回报再通过系统订单号定位订单。只比较 OrderRef，无法排除其他会话的相同编号。订单提交返回零仅表示请求被接口接受，不等于柜台受理，更不等于成交。[^ctp]

从异步回报得到的工程要求是：持久记录发单意图与订单归属，按稳定成交标识去重，恢复时查询订单、成交和目标持仓并等待查询完成。查询未返回、超时和零条已完成查询是不同状态。课程补交标准也将开仓成交、平仓成交与最终查询列为分别核验的证据。[^acceptance]

| 观察 | 可以证明 | 还需补充 |
|---|---|---|
| 发单函数返回 | 本地接口接受请求 | 委托回报、成交回报 |
| 开仓成交 | 已产生对应头寸 | 平仓与撤单处理 |
| 平仓成交 | 已执行对应平仓 | 查询确认最终状态 |
| 最终查询完成 | 当次查询的持仓与委托状态 | 与持久账本核对、记录时序 |

SHFE/INE 的平仓要区分今仓、昨仓。`PositionHolding.convert_order_request_shfe` 先扣除冻结数量，数量不足时返回空列表；有今仓时优先生成平今，剩余部分平昨。假设有今仓 2 手、昨仓 3 手且均未冻结，卖平 4 手会拆成平今 2 手、平昨 2 手；若可用仓位只有 3 手，同一请求则返回空列表。这是对函数分支的手工追踪。[^offset]

撤单请求和成交回报走不同的异步路径，因此程序需要处理撤单与晚到成交交错的情形。停止策略、发出撤单、持仓归零分别表示不同的状态。最终核对目标多头、空头和活动委托时，应分别检查数量，不能用多空相抵的净仓位替代。[^ctp][^acceptance]

[返回目录](index.md) · [策略接口与生命周期](vnpy-ctastrategy.md)

## 参考

[^template]: VeighNa, [template.py，buy/sell/short/cover 与 send_order](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/template.py#L148)。
[^send]: VeighNa, [engine.py，send_order](https://github.com/vnpy/vnpy_ctastrategy/blob/7a8768de9784dda35a7b261a7ade1dbfbff50919/vnpy_ctastrategy/engine.py#L470)。
[^main]: VeighNa, [MainEngine.send_order](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/engine.py#L265)。
[^ctp]: VeighNa, [CtpTdApi.onRtnOrder/onRtnTrade](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/gateway/ctp_gateway.py#L671)。
[^offset]: VeighNa, [convert_order_request_shfe](https://github.com/vnpy/vnpy/blob/c6e231caf32b7fc97e6459817fff66458cf7e7c4/vnpy/trader/converter.py#L192)。
[^acceptance]: aslan9, [第二讲作业阶段性评阅，统一补交标准](https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-6034194088)，2026-10-07。
