# 第二讲作业

本作业包括 VeighNa 源码学习、底层 CTP 仿真交易和 A 股跨股票领先—滞后因子研究。代码、测试、冻结配置和验收证据均在本仓库；[依赖与独立复现](DEPENDENCIES.md)说明两个包的安装和统一离线核验。

| 内容 | 文档与证据 |
|---|---|
| 源码学习 | [Wiki 目录](docs/veighna/index.md)：`vnpy`、`vnpy_ctp`、`vnpy_ctastrategy`，固定源码版本与行号引用 |
| SimNow 仿真 | [验收记录](evidence/lesson02/README.md)：一手开仓、平仓成交及最终查询；[代码与复现](projects/ctp_assignment/README.md) |
| 因子研究 | [研究报告](studies/literature-factor-20261009/package/SUBMISSION.md)、[中文摘要](studies/literature-factor-20261009/package/SUMMARY_ZH.md)、[六个实测方案](studies/literature-factor-20261009/README.md) |
| 评阅核对 | [统一验收清单](evidence/lesson02/review-checklist.md)、[实际命令与退出码](evidence/lesson02/commands.jsonl)、[校验值](evidence/lesson02/checksums.sha256) |

2026 年 10 月 9 日北京时间 13:04:12，SimNow 中 T2612 一手买开成交价 109.420，卖平成交价 109.415。完整查询及独立只读重连均确认目标多头 0、空头 0、活动委托 0。CTP 的 77 项离线测试、因子的 33 项离线测试通过；[命令与结果](evidence/independence/offline-verification.json)可核对。

因子采用预定排名规则选出的 `NET_K20_A02`，验证资格为 `false`。七个交易日账户毛收益 −0.900%、净收益 −1.230%，基准净收益 −0.479%；样本与既往接触范围见报告。
