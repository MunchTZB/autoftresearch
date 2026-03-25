# autoftresearch — 项目计划

> 基于 [karpathy/autoresearch](https://github.com/karpathy/autoresearch) 的理念，
> 使用 freqtrade 框架进行自主量化策略研究。
>
> 核心思想：AI Agent 负责策略架构决策，hyperopt 负责参数优化，
> 人类编写 program.md 来"编程"研究方向。

---

## 1. 项目结构

```
autoftresearch/
├── prepare.py              # 固定：数据准备、回测 pipeline、评估函数（不可修改）
├── strategy.py             # Agent 唯一修改的文件：策略逻辑
├── program.md              # Agent 指令：研究方向与约束（人类编写）
├── config.json             # freqtrade 配置（固定的回测参数）
├── pyproject.toml          # 依赖管理（uv）
├── results.tsv             # 实验日志（Agent 记录，不纳入 git）
├── README.md               # 项目说明
└── user_data/
    ├── data/               # 历史 K 线数据（由 prepare.py 下载）
    └── strategies/         # freqtrade 策略目录（prepare.py 自动同步 strategy.py）
```

---

## 2. 三个核心文件的职责

### 2.1 `prepare.py`（固定，Agent 不可修改）

负责所有"基础设施"：

- **数据下载**：通过 freqtrade 的 `download-data` 命令获取历史 K 线
- **策略同步**：将 `strategy.py` 复制到 `user_data/strategies/`
- **Hyperopt 运行**：以固定 epochs 运行参数优化
- **回测执行**：用 hyperopt 最优参数进行回测
- **结果评估**：从回测结果中计算综合评分并输出标准格式
- **Train/Test 分割**：定义训练集（hyperopt）和测试集（backtest），防止过拟合

关键设计 — 数据分割：

```
|<----------- 历史 K 线数据 ----------->|
|                                       |
|  训练集 (TRAIN)     |  测试集 (TEST)  |
|  2022-01 ~ 2024-01  |  2024-01 ~ 2025-01  |
|                      |                |
|  hyperopt 在这里     |  backtest 在这里    |
|  搜索最优参数        |  用最优参数评估策略  |
```

- **训练集**：hyperopt 用来搜索参数的数据。Agent 不直接看到这段数据上的回测结果。
- **测试集**：用 hyperopt 找到的最优参数进行 backtest，产生最终评估指标。这是 Agent 决定保留/回滚的唯一依据。

```python
# 固定常量
TRAIN_TIMERANGE = "20220101-20240101"   # 训练集：hyperopt 用此段数据搜索参数
TEST_TIMERANGE  = "20240101-20250101"   # 测试集：用最优参数在此段数据上 backtest
HYPEROPT_EPOCHS = 500                    # hyperopt 迭代次数
PAIRS = ["BTC/USDT", "ETH/USDT", ...]  # 交易对
STAKE_CURRENCY = "USDT"
STARTING_BALANCE = 1000
MIN_TRADES = 20                          # 测试集上最低交易次数阈值
```

输出格式（与 autoresearch 对齐）：

```
---
test_score:        1.8500
test_sharpe:       1.92
test_max_drawdown: -0.1200
test_profit_pct:   35.20
test_trade_count:  87
hyperopt_epochs:   500
hyperopt_best_loss: -2.1000
total_seconds:     423.5
```

### 2.2 `strategy.py`（Agent 唯一修改的文件）

一个标准的 freqtrade `IStrategy` 子类。Agent 可以修改的范围：

- **技术指标选择与组合**：RSI、MACD、BB、EMA、ATR、Volume 指标等
- **进场信号逻辑**：条件组合、多重确认机制
- **出场信号逻辑**：止盈条件、趋势反转检测
- **止损/止盈机制**：固定止损 vs 追踪止损 vs 动态止损
- **仓位管理**：`custom_stake_amount` 回调
- **时间框架**：`timeframe` 属性
- **Hyperopt 搜索空间定义**：`DecimalParameter`、`IntParameter`、`CategoricalParameter`
- **自定义回调**：`custom_exit`、`confirm_trade_entry` 等

Agent **不应该**做的：

- 直接硬编码参数值（应该用 `Parameter` 让 hyperopt 优化）
- 修改 `prepare.py`
- 安装新依赖

### 2.3 `program.md`（人类编写，给 Agent 的指令）

定义研究方向、约束和流程。内容包括：

- 实验 setup 流程（分支命名、数据检查等）
- 实验循环的详细步骤
- 什么可以做、什么不能做
- 策略评估标准和简洁性原则
- 领域知识提示（避免过拟合、交易次数要求等）

---

## 3. 实验循环

```
LOOP FOREVER:
  1. 查看 git 状态和历史实验日志 (results.tsv)
  2. 提出策略假设（结构性修改，非参数调整）
  3. 修改 strategy.py
  4. git commit
  5. 运行：uv run prepare.py evaluate > run.log 2>&1
     → prepare.py 内部执行两步：
       STEP 1 — Hyperopt（训练集）
         在 TRAIN_TIMERANGE 上运行 hyperopt，搜索策略参数的最优值。
         产出：一组最优参数。
       STEP 2 — Backtest（测试集）
         将 hyperopt 找到的最优参数应用到策略上，
         在 TEST_TIMERANGE 上运行 backtest。
         产出：Sharpe、回撤、收益率、交易次数等指标 → 计算 test_score。
  6. 解析结果：grep "^test_score:" run.log
  7. 如果 test_score 改善 → 保留 commit，记录到 results.tsv
     如果 test_score 退步 → git reset，记录 discard 到 results.tsv
     如果崩溃 → 尝试修复或跳过，记录 crash
  8. 回到 1
```

为什么这样分两步：
- Hyperopt 在训练集上搜索参数，相当于"学习"。
- Backtest 在测试集上评估，相当于"考试"。
- Agent 只看到"考试成绩"(test_score) 来决定策略好坏，避免参数过拟合训练集。

---

## 4. 评估指标

### 4.1 综合评分函数

```python
def compute_score(backtest_results):
    sharpe = results['sharpe_ratio']
    max_drawdown = results['max_drawdown']       # 负数，如 -0.12
    profit_pct = results['profit_total_pct']
    trade_count = results['trade_count']

    # 交易次数不足，策略不可信
    if trade_count < MIN_TRADES:
        return -999.0

    # 综合评分：以 Sharpe 为基础，惩罚大回撤
    # score > 0 为正常策略，越高越好
    score = sharpe * (1 + profit_pct / 100) * (1 + max_drawdown)
    return score
```

### 4.2 过拟合防护

- **Train/Test 时间分割**：hyperopt 仅使用 TRAIN_TIMERANGE 数据搜索参数，最终评估仅在 TEST_TIMERANGE 上进行 backtest
- **Agent 只看到 test_score**：hyperopt 内部的 loss 不暴露给 Agent 决策
- **交易次数阈值**：测试集上低于 MIN_TRADES 的策略直接判负
- **可选**：保留一个 holdout period（如 2025-01 ~ 2025-06），Agent 完全无法触及，人工定期检查

---

## 5. 与 autoresearch 的设计对比

| 维度 | autoresearch | autoftresearch |
|------|-------------|----------------|
| 被修改的文件 | `train.py`（模型+训练） | `strategy.py`（策略逻辑） |
| 评估方式 | 直接训练 5 分钟 | hyperopt + backtest |
| Agent 角色 | 架构师 + 调参师 | 仅架构师（调参交给 hyperopt） |
| 时间预算 | 固定 5 分钟 | hyperopt epochs 固定（时间因机器而异） |
| 评估指标 | val_bpb（单一，越低越好） | 综合评分（Sharpe×收益×回撤，越高越好） |
| 过拟合防护 | 验证集 | Train/Test 时间分割（hyperopt 训练集 + backtest 测试集） |
| 每晚实验数 | ~100 | ~20-50（hyperopt 更耗时） |
| 运行环境 | 单 GPU | 本地机器（CPU 密集） |

---

## 6. 技术栈与依赖

### Python 版本

```
>= 3.11（推荐 3.12）
```

### 包管理器

```
uv
```

### pyproject.toml

```toml
[project]
name = "autoftresearch"
version = "0.1.0"
description = "Autonomous quantitative strategy research using freqtrade"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "freqtrade>=2026.2",
    "pandas-ta>=0.3.14b",
    "matplotlib>=3.9.0",
    "tabulate>=0.9.0",
]

[project.optional-dependencies]
analysis = [
    "plotly>=5.0",
    "ipykernel",
    "jupyter",
]
```

### 依赖说明

| 依赖 | 作用 |
|---|---|
| `freqtrade` | 量化框架核心（自带 ccxt、pandas、numpy、SQLAlchemy） |
| `pandas-ta` | 130+ 技术指标，纯 Python，Agent 直接调用 |
| `matplotlib` | 结果可视化 |
| `tabulate` | 实验日志表格化输出 |

---

## 7. 运行环境要求

- 本地机器，CPU 多核（hyperopt 受益于多核并行）
- 如果后续引入 FreqAI，则需要 GPU
- 稳定网络（首次下载历史数据时需要）
- 磁盘空间：历史数据约 1-5 GB（取决于交易对和时间范围）

---

## 8. 实现步骤

### Phase 1：基础骨架
- [ ] 创建 `pyproject.toml`，`uv sync` 安装依赖
- [ ] 创建 `config.json`（freqtrade 回测配置）
- [ ] 创建 `prepare.py`（数据下载 + 评估 pipeline）
- [ ] 创建 `strategy.py`（基线策略模板）
- [ ] 手动运行一次完整流程验证 pipeline

### Phase 2：评估系统
- [ ] 实现 `prepare.py` 中的 hyperopt 调用
- [ ] 实现 `prepare.py` 中的 backtest 调用和结果解析
- [ ] 实现综合评分函数 `compute_score`
- [ ] 实现 Train/Test 时间分割（hyperopt 用训练集，backtest 用测试集）
- [ ] 实现标准输出格式（与 autoresearch 对齐）

### Phase 3：Agent 指令
- [ ] 编写 `program.md`（参考 autoresearch 的 program.md）
- [ ] 定义实验 setup 流程
- [ ] 定义实验循环规则
- [ ] 定义 results.tsv 格式和记录规则

### Phase 4：验证与迭代
- [ ] 用 AI Agent 跑第一轮自主实验（5-10 个）
- [ ] 检查实验日志，评估 Agent 行为是否合理
- [ ] 根据结果迭代 program.md
- [ ] 检查 holdout period 结果，确认无严重过拟合

---

## 9. 风险与注意事项

1. **过拟合**：量化策略极易过拟合历史数据。Train/Val 分割是最低保障，定期人工审查 holdout 数据仍然必要。
2. **策略复杂度膨胀**：Agent 可能倾向于堆叠指标。在 program.md 中设置简洁性原则（与 autoresearch 一致）。
3. **Hyperopt 局部最优**：固定 epochs 可能不够。需要观察 hyperopt 收敛情况并调整。
4. **数据质量**：免费交易所数据可能有缺失或异常。首次运行后需检查数据完整性。
5. **Lookahead bias**：策略代码中意外使用了未来数据。freqtrade 有内置检查，但仍需留意。
