# vnpy_ctp：从原生接口到网关事件

固定提交：`1be9bfb5292208e5c258cc769c90be4abe83f9a9`。

这一模块有两层接口：底层 C++/pybind11 包装把 CTP 的结构体和 SPI 回调转换为 Python 可用的字典及方法；Python 网关再把这些数据转换成 vnpy 的标准对象。直接继承 MdApi/TdApi 与使用 CtpGateway，是不同层次的入口。[^bridge][^gateway]

包装层的 Task 保存回调类型、数据、错误、请求号和结束标志。TaskQueue 使用互斥锁与条件变量传递任务。以行情为例，`OnRtnDepthMarketData` 复制数据并入队；`processTask` 分发任务；`processRtnDepthMarketData` 取得 GIL、建立字典并调用 Python 回调。这里的队列发生在 VeighNa EventEngine 之前。[^queue][^bridge]

| 路径 | 固定源码中的主要步骤 | 回报的含义 |
|---|---|---|
| MD | 连接 → 登录回报 → 订阅 → 深度行情回报 | 行情会话与行情数据 |
| TD | 连接 → 认证（配置要求时）→ 登录 → 结算确认 → 合约查询 | 交易会话与合约状态 |
| 发单 | OrderRequest → 字典 → reqOrderInsert | 异步请求已送交接口 |
| 委托、成交 | onRtnOrder / onRtnTrade → 标准对象 → 网关事件 | 订单变化与实际成交 |

MD 登录回报恢复已有订阅。TD 登录回报保存 FrontID 和 SessionID，再发起结算确认。合约查询到齐后，网关才处理依赖合约信息的缓存回报。这解释了为什么“TCP 已连接”“登录成功”“合约可用”不是一个状态。[^md][^td][^contract]

订单标识包含 FrontID、SessionID、OrderRef；交易所系统订单号另外映射到本地订单号。成交路径直接使用该映射，因此阅读回报顺序时要同时追踪映射何时建立。把这些关系写清楚，比只观察发单函数返回值更能说明订单归属。[^orders]

请求字典还经过类型和字符串拷贝。该固定版本的 `getString` 使用 strcpy 写入 CTP 固定长度字段，调用方应在进入包装层前校验长度与类型；Python 字典可以装下任意长度字符串，并不意味着原生字段也可以。[^queue]

[标准对象与事件](vnpy.md) · [委托、成交与对账](orders-and-reconciliation.md) · [返回目录](index.md)

## 参考

[^queue]: VeighNa, [vnctp.h](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/api/vnctp/vnctp.h#L22)，Task、TaskQueue、getString。
[^bridge]: VeighNa, [vnctpmd.cpp](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/api/vnctp/vnctpmd/vnctpmd.cpp#L196)，`OnRtnDepthMarketData`、`processTask`、`processRtnDepthMarketData`。
[^gateway]: VeighNa, [CtpGateway](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/gateway/ctp_gateway.py#L169)，连接、订阅和请求转发。
[^md]: VeighNa, [MD 登录回报与订阅](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/gateway/ctp_gateway.py#L286)。
[^td]: VeighNa, [TD 认证、登录和结算确认](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/gateway/ctp_gateway.py#L477)。
[^contract]: VeighNa, [合约查询回报](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/gateway/ctp_gateway.py#L624)。
[^orders]: VeighNa, [订单和成交回报](https://github.com/vnpy/vnpy_ctp/blob/1be9bfb5292208e5c258cc769c90be4abe83f9a9/vnpy_ctp/gateway/ctp_gateway.py#L671)。
