## 第二讲作业

[作业仓库](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/) · [源码 Wiki](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/docs/veighna/index.md) · [SimNow 验收记录](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/README.md) · [因子研究报告](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/studies/literature-factor-20261009/package/SUBMISSION.md)

### VeighNa 源码学习

围绕 `vnpy`、`vnpy_ctp`、`vnpy_ctastrategy` 阅读标准数据对象、MD/TD 回调、事件分发、OMS 缓存、委托路由、策略接口与交易所平仓规则，并梳理单标的、组合和价差策略的接口分工。八篇学习文档引用固定提交的源码行号；[来源清单](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/docs/veighna/source_manifest.json)记录提交与文件哈希。

### SimNow 一手开平仓

底层 Python MD/TD API 实现持续行情、价格阈值触发、SQLite 意图持久化、成交去重、重启对账和最终验收。默认离线运行；网络命令需要显式 `--simnow` 和仓库外私有配置。计划冻结为 CFFEX 的 T2612，`LastPrice > 109.0` 时最多买开一手，确认成交后卖平。

2026 年 10 月 9 日的实际成交如下，时间为北京时间：

| 北京时间 | 方向 | 手数 | 成交价 | 委托编号 | 成交编号 |
|---|---|---:|---:|---|---|
| 13:04:12 | 买入开仓 | 1 | 109.420 | 388242 | 251873 |
| 13:04:12 | 卖出平仓 | 1 | 109.415 | 388243 | 251874 |

开平仓后完成订单、成交、持仓查询，确认 **目标多头 0、空头 0、活动委托 0**；独立只读重连再次确认。[脱敏柜台回报](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/records/broker-query-evidence.json)保留两笔委托和成交的归属字段及查询完成标志，[持久事件记录](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/records/simnow-live-02.json)可核对发单前意图与最终状态。

行情实测覆盖 IF2612 和 T2612，共 39 次 MD 行情回调，客户端分别采样 20、17 次；最新盘口通过新鲜度检查。开仓前检查登录、结算、合约、保证金、双边费用、行情时效及空仓状态。异常状态停止新敞口，恢复前先对账。完整尝试、预检查停止及适配记录见[运行索引](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/attempts.json)。该阈值用于功能验收，不作收益预测。

### 跨股票领先—滞后因子

方法参考 [Bennett、Cucuringu 和 Reinert（2022）](https://arxiv.org/abs/2201.08283)：以股票 i 前一日收益和股票 j 当日收益的相关性减去反向相关性，估计方向性联系；对每只目标股票保留最强的 K 条入边，再用领先股票收益的指数加权均值生成分数。网络每两个月用此前历史重估，收盘后形成分数，下一交易日执行，每五个交易日调仓。

六个实际测试方案使用相同机制。K 较小更集中，较大覆盖更多关系；α=0.2 保留较长记忆，α=0.4 更重近期变化。

| 方案 | 领先股票数 K | 平滑系数 α | 验证期净主动均值，基点/日 | 选择 |
|---|---:|---:|---:|---|
| `NET_K05_A02` | 5 | 0.2 | −4.965 | 未选 |
| `NET_K05_A04` | 5 | 0.4 | −5.856 | 未选 |
| `NET_K10_A02` | 10 | 0.2 | −4.240 | 未选 |
| `NET_K10_A04` | 10 | 0.4 | −4.506 | 未选 |
| `NET_K20_A02` | 20 | 0.2 | −4.218 | 采用 |
| `NET_K20_A04` | 20 | 0.4 | −4.788 | 未选 |

按预先确定的验证期平均净主动收益排名采用 `NET_K20_A02`，其他五个方案的该指标均较低。六个方案未达到预设验证门槛，选择依据为预定备选规则；`method_selected=NET_K20_A02`，`validation_qualified=false`。

开发期为 2008–2017，验证分为 2018–2019、2020–2021、2022–2023。选定方案覆盖 1,457 个验证日期，净主动均值 −4.218 基点/日，HAC 95% 区间 [−6.286, −2.149]；三个分段均值均为负，18 个预留假设位的 Holm 校正 p 值为 1.000。

冻结方法后的单次期间评价使用 100 万元现金、历史成分、只做多和一致规则的同股票池基准。账户处理整手、停牌、涨跌停、仓位、成交参与率、双边佣金与法定费用、滑点和公司行动；成本、延迟及千万元容量诊断随结果保留。

| 指标 | 2026 年 9 月 21–24、28–30 日 |
|---|---:|
| 交易日 / 成熟 IC 日期 | 7 / 2 |
| 同成交数量毛收益 / 账户净收益 | −0.900% / −1.230% |
| 同股票池基准净收益 / 相对基准复合收益 | −0.479% / −0.755% |
| 日均换手 / 净值最大回撤 | 31.662% / −2.952% |
| 交易费用 / 滑点 / 股息税准备，元 | 1004.60 / 2209.00 / 92.54 |
| 期末现金 / 持仓市值，元 | 59971.56 / 927726.00 |
| 期末持仓数量 | 49 |

毛收益按相同成交数量还原费用、滑点及股息税准备。估值截止 9 月 30 日收盘，保留期末持仓；不使用 10 月 8 日结果。历史区间及部分 9 月日期已在先前工作中接触，独立下载不代表未接触样本。

[CTP 复现说明](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/projects/ctp_assignment/README.md) · [实际命令与退出码](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/commands.jsonl) · [评阅核对](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/review-checklist.md) · [验收证据校验值](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/evidence/lesson02/checksums.sha256) · [因子复现说明](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/studies/literature-factor-20261009/package/REPRODUCE.md) · [研究包及校验值](https://github.com/celestial-toymaker/factor_pku_quantllm_demo/blob/main/studies/literature-factor-20261009/README.md)
