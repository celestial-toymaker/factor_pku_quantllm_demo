# 第二讲作业

本 Wiki 按“底层接口—中层引擎—策略应用”梳理 VeighNa。沿一笔行情和一笔委托追踪数据如何进入系统、如何更新状态，以及策略接口如何使用这些状态。内容依据官方源码的固定提交，逐文件 SHA-256 与永久链接见[源码清单](source_manifest.json)。

| 模块 | 固定版本 | 阅读重点 |
|---|---|---|
| [vnpy](vnpy.md) | `c6e231caf32b7fc97e6459817fff66458cf7e7c4` | 数据对象、事件引擎、MainEngine、OMS、开平转换 |
| [vnpy_ctp](vnpy-ctp.md) | `1be9bfb5292208e5c258cc769c90be4abe83f9a9` | MD/TD 回调、会话、订单标识、Python/C++ 边界 |
| [vnpy_ctastrategy](vnpy-ctastrategy.md) | `7a8768de9784dda35a7b261a7ade1dbfbff50919` | 策略生命周期、委托路由、去重、回测撮合 |

- [行情与事件链](events-and-data.md)：从 CTP Tick 到标准数据和策略回调。
- [委托、成交与对账](orders-and-reconciliation.md)：请求与回报的区别，持久化和最终空仓条件。
- [策略应用与回测边界](strategy-applications.md)：单标的、投组、价差应用的状态要求。
- [阅读与核对方法](reading-guide.md)：如何按源码复核调用链、对象和边界。
- [核对记录](verification.json)：来源哈希、引用、链接与发布文件范围。

建议先读三个模块页，再沿行情与委托两条链回查代码。应用比较属于架构分析，回测部分依据已定位的撮合函数说明其假设。

[返回作业首页](../../README.md) · [因子研究](../../studies/literature-factor-20261009/README.md)
