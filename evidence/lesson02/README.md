# 第二讲作业：SimNow 验收记录

[作业首页](../../README.md) · [CTP 代码与复现](../../projects/ctp_assignment/README.md) · [源码 Wiki](../../docs/veighna/index.md) · [评阅核对](review-checklist.md)

## 实际开平仓与最终查询

2026 年 10 月 9 日，官方 SimNow 第一套环境，CFFEX 合约 **T2612**。冻结条件为 `LastPrice > 109.0`，买开最多一手；确认开仓成交后卖平。阈值用于检验程序闭环，不是收益预测方法。

| 北京时间 | 方向 | 手数 | 成交价 | 委托编号 | 成交编号 |
|---|---|---:|---:|---|---|
| 13:04:12 | 买入开仓 | 1 | 109.420 | 388242 | 251873 |
| 13:04:12 | 卖出平仓 | 1 | 109.415 | 388243 | 251874 |

两笔委托的 `OrderStatus=0`，各成交一手。CFFEX 使用普通平仓标志 `CLOSE`。开平回报之后，订单、成交及持仓查询均收到成功的最后一条响应，目标多头 **0**、空头 **0**、活动委托 **0**。独立只读重连再次满足相同条件。

[柜台字段证据](records/broker-query-evidence.json)通过 FrontID、SessionID、OrderRef、OrderSysID 与本地持久账本匹配，保留委托、成交编号及查询完成回调。它单独查询，发单数为 0。[执行记录](records/simnow-live-02.json)与[只读重连记录](records/simnow-reconcile-01.json)的验收结果均为 `PASS`。这里报告功能验收；未导出精确逐笔手续费结算，因此仿真净损益为空，不以价差代替净收益。

## 行情和执行规则

[双合约行情记录](records/cffex-quotes-03.json)包含 IF2612 与 T2612：MD 行情回调共 **39** 次，客户端循环分别采样 **20**、**17** 次。采样次数与批量到达的 API 回调次数采用不同口径；两份最新盘口均通过新鲜度检查，柜台产品状态均为连续交易。

计划在下单前冻结，哈希为 `61cb0c814d202d1b52d71b182675e1f327f88b7baad0b3cc97308b2724e357f4`。本地行情接收年龄须在 0–3 秒，源时间年龄在 −1–3 秒，允许最多 1 秒源时钟提前；边界已离线测试。预检查还要求登录与结算完成、合约有效、保证金和双边费用查询成功、多空目标持仓为零且没有活动委托。

SQLite 在发单前保存意图，进程独占锁、会话映射及成交去重共同限制重复开仓。单笔订单十秒未终结则请求撤单，再等十秒仍未知则停止新委托；整体触发窗口 120 秒。减仓重试最多三次，须先确认旧委托终结和剩余持仓。状态未知、断线、超时或拒单均停止新敞口。离线测试覆盖撤单后晚到成交、重复及乱序回调、重启恢复、查询完成与交易所平仓标志。

## 完整运行记录

[尝试索引](attempts.json)和[命令台账](commands.jsonl)保留已记录的运行，包括连通性检查、休市行情及预检查停止。早于命令记录器的连接检查没有完整命令或退出码，相关字段为空并注明原因。

第一次有界执行在保证金/费用字段检查处停止，开平仓意图与成交均为零。柜台返回的精确 T2612 风险记录中 ExchangeID 为空；适配器允许精确合约/产品匹配且缺省交易所的记录，显式冲突仍拒绝。修正后重新记录源码哈希并继续使用同一账本，合约、阈值和账户限制未变。完整事件序列只有一个开仓意图。

原始[冻结记录](records/frozen-plan.json)、[执行前源码冻结](records/frozen-plan-v2.json)、[首次执行](records/simnow-live-01.json)及[柜台字段投影](records/risk-fields-01.json)可相互核对。修正前后的记录均保留。

因子包的命令校验在独立副本中运行，[结果](logs/factor-cli-verify-02.log)为通过；未导入包路径的第一次命令及退出码也保留在台账中。归档校验仅核对原模块、指标与文件哈希，不执行组合评价。

## 环境和复现

| 层次 | 已执行的检查 |
|---|---|
| 环境 | Python 3.13.5，Apple Silicon；[确切版本](environment.json)、[依赖锁](../../projects/ctp_assignment/requirements.lock) |
| 全新安装 | 新建 release-env，按锁安装并安装本项目；三条命令退出码均为 0 |
| 原生编译 | [build-05 命令](native/build-05/commands.json)与[产物哈希](native/build-05/build_manifest.json)，退出码均为 0 |
| API 导入 | [doctor](records/doctor-fresh-01.json)成功，MD/TD 均为 CTP 6.7.13；此命令网络连接数为 0 |
| 离线模拟 | [独立合成例子](records/dry-run-01.json)，状态 `OFFLINE_PASS`；手算毛损益 −10、双边费用 4、净损益 −14 |
| CTP 测试 | [77 passed](logs/release-tests-01.log)，[实际命令](commands/release-tests-01.json)退出码 0 |
| 因子测试 | 当前 [33 passed](../independence/offline-verification.json)；此前 [30 项记录](logs/factor-tests-01.log)与[命令](commands/factor-tests-01.json)保留；未重开最终评价 |
| 行情及交易 | 独立的网络记录见上文；编译、导入及离线通过不代替成交验收 |

实际连接使用已获 macOS 允许的 build-02 路径；[其构建清单](native/build-02/build_manifest.json)与 build-05 的重新编译记录分别保留，不把两者当成同一产物。SDK 压缩包、原件哈希和包装源码版本均写入构建清单。源码学习的三仓库固定版本见 [source_manifest.json](../../docs/veighna/source_manifest.json)。

命令中的 `$REPO` 是此仓库，`$WORK` 是仓库外本地工作目录，`$SDK` 是独立取得的官方 SDK，`$FACTOR_WORK` 是原因子环境，`$WORKSPACE` 是工作区。原生输出先写入私有日志，只发布字段白名单和脱敏测试/构建日志。配置样例没有账户值，数据库、flow 文件和完整资金快照留在本地。

离线校验已发布的验收证据：

```sh
cd projects/ctp_assignment
.venv/bin/ctp-assignment verify ../../evidence/lesson02/records/simnow-live-02.json
.venv/bin/ctp-assignment verify ../../evidence/lesson02/records/simnow-reconcile-01.json
cd ../../evidence/lesson02
shasum -a 256 -c checksums.sha256
```

汇总数据来自 [status.json](status.json)，逐文件校验值见 [checksums.sha256](checksums.sha256)。因子研究的原科学模块、冻结记录与已有结果保持原值；研究结论和仿真功能验收分别记录。
