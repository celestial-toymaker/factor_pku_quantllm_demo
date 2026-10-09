# 阅读与核对方法

先用[源码清单](source_manifest.json)确定仓库、提交和文件，再用页面脚注跳到对应函数。固定提交链接可以避免主分支更新后出现“笔记描述与源码不一致”。清单中的 SHA-256 对应下载后未修改的原始文件字节，包括原有换行符。

| 问题 | 起点 | 沿调用链检查 |
|---|---|---|
| 行情怎样到达策略？ | CtpMdApi.onRtnDepthMarketData | TickData → BaseGateway.on_tick → EventEngine → CtaEngine.process_tick_event |
| 发单经过哪些层？ | CtaTemplate.buy/sell | 模板 send_order → CtaEngine → MainEngine → CtpGateway → 原生请求 |
| 订单与成交如何关联？ | CtpTdApi.onRtnOrder | 会话与 OrderRef → OrderSysID 映射 → onRtnTrade |
| 谁保存最新状态？ | OmsEngine.process_*_event | 标准对象缓存、活动委托集合、OffsetConverter |
| 平今平昨怎样选择？ | PositionHolding.convert_order_request_shfe | 总可用量、今仓可用量、冻结数量、拆单返回值 |
| 回测怎样成交？ | BacktestingEngine.cross_limit_order | 穿越条件、开盘价改善、一次填满数量、回调顺序 |

这些入口的源码定位分别见[行情链](events-and-data.md)、[委托链](orders-and-reconciliation.md)和[策略应用](strategy-applications.md)。复核时不仅阅读函数名和注释，也检查分支条件、状态写入位置及调用者如何使用返回值。

本文档区分三类内容：官方源码可直接支持的行为、沿给定参数手工追踪的分支示例，以及由状态约束推导的架构分析。多标的与价差部分使用第三类表述，不把架构比较写成收益或交易实验结论。

核对流程为：逐文件比对已记录的哈希；确认源码脚注包含固定提交与有效行号；检查所有本地链接和脚注配对；检查发布清单只包含本次 Wiki 与导航更新。结果见[verification.json](verification.json)。

[返回目录](index.md)
