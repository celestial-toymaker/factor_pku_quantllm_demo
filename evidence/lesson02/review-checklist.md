# 第二讲作业：评阅核对

核对依据：[课程评阅的统一补交标准](https://github.com/aslan9/pku_quantllm/issues/2#issuecomment-6034194088)。

| 标准 | 实际证据与边界 |
|---|---|
| SimNow 一手闭环 | [执行事件](records/simnow-live-02.json)包括持久化开仓意图、归属明确的两笔成交和完整最终查询；[只读柜台查询](records/broker-query-evidence.json)确认多头 0、空头 0、活动委托 0 |
| 异常停止与恢复 | [77 项测试](logs/release-tests-01.log)覆盖重复/乱序回报、撤单后成交、持久账本恢复、查询最后一条标志、拒单、断线、未知状态、保证金不足与时效限制；这些为离线故障注入，实际网络验收只声明已发生的开平仓和查询 |
| 账户安全 | [空值样例](../../projects/ctp_assignment/config/simnow.example.json)；凭据、完整资金快照、数据库和原生 flow 不进入发布目录；[发布检查](verification.json)记录工作树、可达 Git 历史与 ZIP 成员扫描 |
| 可复现性 | [依赖锁](../../projects/ctp_assignment/requirements.lock)、[实际命令与退出码](commands.jsonl)、[版本](environment.json)、[构建](native/build-05/commands.json)、[脱敏日志](logs/release-tests-01.log)；编译、离线模拟、行情和交易分别证明 |
| 源码学习 | [Wiki](../../docs/veighna/index.md)覆盖标准数据、MD/TD 回调、事件分发、OMS 缓存、委托路由、策略接口与平仓；三仓库的固定提交和源文件哈希可核对 |
| 因子冻结与全部尝试 | [协议及最终冻结](../../studies/literature-factor-20261009/package/configs/)、[实验台账](../../studies/literature-factor-20261009/package/research/experiment_ledger.jsonl)、[六个实测方案](../../studies/literature-factor-20261009/package/SUMMARY_ZH.md)；没有继续增加候选或重开最终评价 |
| 真实摩擦与统计 | [统一报告](../../studies/literature-factor-20261009/package/SUBMISSION.md)列毛净收益、换手、最大回撤、双边费用、历史印花税、滑点、停牌/涨跌停、容量和只做多现金限制；历史使用 HAC 与 Holm，最终七日置信区间为空并注明样本不足 |
| 既往接触 | [研究摘要](../../studies/literature-factor-20261009/package/SUMMARY_ZH.md)说明历史和部分 9 月日期已有接触；独立下载不等于未接触样本，七日结果不作年化 |

此清单核对所提交的作业证据，不把单次仿真闭环解释为盈利能力或生产系统可靠性证明。因子验证资格与打包、发布状态分别记录。
