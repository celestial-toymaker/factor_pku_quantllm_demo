# CTP 一手仿真闭环

本程序从 `vnpy_ctp` 底层 Python MD/TD API 开始，提供持续行情、阈值触发、持久账本、开平仓、重启对账与验收导出。仅支持官方已核实的 SimNow 地址，单次冻结计划最多一手买开；开仓已成交且订单状态确认后卖平。阈值条件为 `LastPrice > trigger_price`，不声称具有预测收益能力。

当前证据见[作业验收记录](../../evidence/lesson02/README.md)。离线合成成交记为 `OFFLINE_PASS`；只有真实 SimNow 回报与最终查询满足条件才记为 `PASS`。命令退出码：0 表示该命令完成，2 表示输入或验收条件未满足，3 表示未预期程序错误。`doctor` 或 `inspect` 返回 0 不表示完成交易闭环。

## 离线复现

在本目录运行；Python 固定为 3.13.5。全量构建环境依赖版本见 [requirements.lock](requirements.lock)，SDK 二进制由使用者从官方单独取得。

```sh
uv venv --python 3.13.5 .venv
uv pip sync --python .venv/bin/python requirements.lock
uv pip install --python .venv/bin/python --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest -q
.venv/bin/ctp-assignment doctor
.venv/bin/ctp-assignment run --state /tmp/lesson02-example/state.db --output /tmp/lesson02-example/evidence.json
.venv/bin/ctp-assignment verify /tmp/lesson02-example/evidence.json
```

每次独立离线例子使用新的状态目录；相同目录用于验证恢复，不能删除真实仿真账本后重试。默认 `run` 不读取凭据、不加载 SDK、不访问网络。合成例子的手算为：101 买入、100 卖出，合约乘数 10，双边费用各 2，毛损益 −10、费用 4、净损益 −14。

## 原生构建

已实现的构建目标是 Apple Silicon、Python 3.13.5、macOS CTP 6.7.13。官方包装源码固定在 `1be9bfb5292208e5c258cc769c90be4abe83f9a9`。该包装版本号为 6.7.11.5；本地编译时同时使用 6.7.13 的头文件与动态库，修正 macOS 登录函数的两参数签名，不混用旧头文件和新库。6.7.13 新增而旧包装未暴露的接口不在本作业调用范围。

```sh
.venv/bin/python scripts/fetch_sources.py /tmp/lesson02-source
.venv/bin/python scripts/build_native.py \
  --source /tmp/lesson02-source/vnpy_ctp-1be9bfb5292208e5c258cc769c90be4abe83f9a9 \
  --sdk /absolute/path/to/macOS_API_6.7.13 \
  --work /tmp/lesson02-build
.venv/bin/ctp-assignment doctor --native-dir /tmp/lesson02-build/native
```

构建脚本核对 SDK 压缩包哈希，保留原件，输出命令、退出码、编译日志和构建清单。macOS 可能要求用户在系统设置中批准官方开发者框架；程序不关闭系统安全检查。新路径上的批准与普通 Python 导入测试分别记录。

## 账户与只读连接

将空值[配置模板](config/simnow.example.json)复制到仓库以外的私有目录，目录权限 700、文件权限 600。真实状态账本与配置放在同一私有目录，共用账户进程锁。`user_id` 填官网个人中心的“投资者代码”。密码、AppID 和认证信息只填入本地文件。`endpoints_verified_on` 记录核对官方连接页的日期，超过七天必须复核。模板不含任何账户或认证值。

2026-10-09 从[官方产品页](https://www.simnow.com.cn/product.action)核实：第一套环境在 `182.254.243.31`，TD/MD 对应端口为 30001/30011、30002/30012、30003/30013；第二套环境为 40001/40011。第二套环境有新账户等待期并不提供同等结算服务。本作业默认采用第一套环境。SDK 的 `production_mode=True` 指监管密钥模式；模拟/实盘隔离由严格的地址与 BrokerID 白名单决定。

以下网络命令从私有工作目录运行，使用环境中命令的绝对路径，避免原生库在源码目录生成运行状态。

```sh
cd /private/path
/absolute/path/to/ctp-project/.venv/bin/ctp-assignment inspect --simnow --config /private/path/simnow.json \
  --native-dir /tmp/lesson02-build/native --output /tmp/inspect.json
/absolute/path/to/ctp-project/.venv/bin/ctp-assignment quotes --simnow --config /private/path/simnow.json \
  --native-dir /tmp/lesson02-build/native --symbols VERIFIED_CONTRACT_1 VERIFIED_CONTRACT_2
```

`inspect` 登录并查询合约，不发送委托。行情命令默认持续输出，Ctrl-C 停止；`--seconds 20` 可生成有限时长的验收记录。符号应来自当前合约查询，示例占位符不能直接交易。原生 API 工作目录和 flow 文件必须在私有目录，不能从源码仓库工作目录启动账户连接。

## 冻结、执行与恢复

先核实当前合约、盘口和交易时段，再在私有配置中写入 `instrument`、`exchange`、`trigger_price`。首次执行把计划哈希及账户绑定写入 SQLite；已有账本拒绝改变规则或账户。预检查要求合约有效、柜台状态为连续交易、行情新鲜、保证金与费用查询完成、目标多空持仓均为零、账户无活动委托。行情本地接收年龄限制为 0–3 秒，源时间允许最多提前 1 秒的时钟偏差，过旧或更远未来的时间均拒绝；该范围写入冻结计划。

```sh
cd /private/path
/absolute/path/to/ctp-project/.venv/bin/ctp-assignment run --simnow --config /private/path/simnow.json \
  --native-dir /tmp/lesson02-build/native --state /private/path/state.db \
  --output /tmp/simnow-evidence.json
/absolute/path/to/ctp-project/.venv/bin/ctp-assignment reconcile --simnow --config /private/path/simnow.json \
  --native-dir /tmp/lesson02-build/native --state /private/path/state.db \
  --output /tmp/reconciliation.json
```

`reconcile` 只查询，不发单；`run` 恢复已有意图时禁止再次开仓。单笔十秒未终结即请求撤单，再等十秒仍未知则停止自动发单。整体触发窗口 120 秒，之后只做有界的撤单/对账/减仓处理；平仓最多三次，每次替换前要确认旧单终结与剩余持仓。不能平仓时保留明确未完成状态与原账本。

SHFE/INE 当日往返使用平今；其他支持市场使用普通平仓。跨交易日恢复保留待核对状态。取消回报不能覆盖晚到成交；重复回报不能制造新的成交或开仓。最终成功要求开仓一手、平仓一手，随后完整查询证明目标多头和空头均为零且无活动委托。

## 代码和证据

- `core.py`：纯控制器、持久化意图、幂等成交、独占锁。
- `native.py`：低层 API 会话、串行查询、回调收集。
- `runner.py`：预检查、执行、恢复和合成手算例子。
- `security.py`：私有配置约束、白名单、导出校验。
- `tests/`：可运行的时序、恢复、会计、身份隔离及查询完成测试。

官方包装与 VeighNa 源码的作者、版本和链接见[源码学习清单](../../docs/veighna/source_manifest.json)。本仓库发布自行编写的适配代码、构建步骤和脱敏证据，不包含用户账户文件、SDK flow 文件或完整资金快照。

额外的只读柜台证据可用 `scripts/query_receipts.py --simnow --config ... --native-dir ... --state ... --output ...` 导出。它按原账本的 FrontID、SessionID、OrderRef 和 OrderSysID 核对两笔委托，只导出白名单内的合约、成交与查询字段。账户、密码、认证信息和资金快照不属于白名单。
