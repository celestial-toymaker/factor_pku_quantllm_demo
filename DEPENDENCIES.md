# 独立复现与依赖

本仓库包含两个独立 Python 包、源码学习文档、合成测试夹具和已记录的验收证据。安装、导入、离线测试及报告核验均不需要任何学生仓库、学生账号或其工作目录。跨股票比较公式在因子包内明确实现；它们不导入或调用外部作业代码。

| 部分 | 本地代码 | 外部要求 |
|---|---|---|
| CTP 离线检查 | `projects/ctp_assignment` | Python 3.13.5；该目录的精确版本依赖锁 |
| 因子离线检查 | `studies/literature-factor-20261009/package` | Python 3.11.11；该目录的精确版本依赖锁 |
| 源码学习与原生构建 | `docs/veighna`、CTP 构建脚本 | 官方 `vnpy`、`vnpy_ctp`、`vnpy_ctastrategy` 固定提交；官方 CTP SDK |
| 真实 SimNow 连接 | 同一 CTP 包 | 用户自己的仿真账户、官方端点和私有本地配置 |
| 经验研究的原输入 | 因子数据接口与指纹 | 合法取得的课程数据及供应商行情；这些不是离线测试的输入 |

官方源码归属、提交与哈希见 [source_manifest.json](docs/veighna/source_manifest.json)。依赖安装来自锁文件指定的公开 Python 包；不使用其他作业的 Git 地址或本地安装路径。原生 SDK、账户文件与受限行情须由使用者独立取得。历史日志中的原机器路径用于说明当时的命令，不是安装或测试的路径要求。

## 两个包的安装

从仓库根目录运行。两个环境分别创建，不能混用 Python 版本。

```sh
uv venv --python 3.13.5 projects/ctp_assignment/.venv
uv pip sync --python projects/ctp_assignment/.venv/bin/python projects/ctp_assignment/requirements.lock
uv pip install --python projects/ctp_assignment/.venv/bin/python --no-deps --no-build-isolation -e projects/ctp_assignment

uv venv --python 3.11.11 studies/literature-factor-20261009/package/.venv
uv pip sync --python studies/literature-factor-20261009/package/.venv/bin/python studies/literature-factor-20261009/package/requirements.lock
uv pip install --python studies/literature-factor-20261009/package/.venv/bin/python --no-deps --no-build-isolation -e studies/literature-factor-20261009/package
```

## 离线核验

不安装项目依赖也可以先用 Python 3.11 或更高版本检查文件、归档与依赖边界：

```sh
python3 scripts/verify_repository.py
```

两个环境安装完成后，运行完整离线检查。验证器将测试和合成模拟放在临时目录中，禁止 Python 网络连接，不读取账户配置、不加载原生 SDK、不下载行情、不重开最终评价，也不改变发布目录的账本与校验值。

```sh
python3 scripts/verify_repository.py \
  --ctp-python projects/ctp_assignment/.venv/bin/python \
  --factor-python studies/literature-factor-20261009/package/.venv/bin/python \
  --output /tmp/lesson02-offline-verification.json
```

因子的冻结协议、科学模块和指标保持原值。公开暴露记录省略来源身份和出版物定位，日期、接触范围及停止规则完整保留；原始哈希与展示副本的差异由 [publication_derivation.json](studies/literature-factor-20261009/package/release/publication_derivation.json)核验。真实 SimNow 的成交与最终空仓证据见 [验收记录](evidence/lesson02/README.md)。

本版离线命令及退出码见 [核验记录](evidence/independence/offline-verification.json)：CTP 77 项、因子 33 项通过。
