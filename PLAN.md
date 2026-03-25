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
- **Train/Val 分割**：定义训练期和验证期，防止过拟合

关键设计：

```python
# 固定常量
TRAIN_TIMERANGE = "20220101-20240101"   # 训练期（hyperopt + 回测用）
VAL_TIMERANGE   = "20240101-20250101"   # 验证期（最终评估用，Agent 看不到训练期结果）
HYPEROPT_EPOCHS = 500                    # hyperopt 迭代次数
PAIRS = ["BTC/USDT", "ETH/USDT", ...]  # 交易对
STAKE_CURRENCY = "USDT"
STARTING_BALANCE = 1000
MIN_TRADES = 20                          # 最低交易次数阈值
```

输出格式（与 autoresearch 对齐）：

```
---
val_score:        1.8500
val_sharpe:       1.92
val_max_drawdown: -0.1200
val_profit_pct:   35.20
val_trade_count:  87
train_score:      2.1000
hyperopt_epochs:  500
total_seconds:    423.5
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
     → prepare.py 内部流程：
       a. 同步 strategy.py → user_data/strategies/
       b. 运行 hyperopt（固定 epochs）→ 最优参数
       c. 用最优参数在训练期回测
       d. 用最优参数在验证期回测
       e. 输出综合评分
  6. 解析结果：grep "^val_score:" run.log
  7. 如果 val_score 改善 → 保留 commit，记录到 results.tsv
     如果 val_score 退步 → git reset，记录 discard 到 results.tsv
     如果崩溃 → 尝试修复或跳过，记录 crash
  8. 回到 1
```

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

- **Train/Val 时间分割**：hyperopt 和训练期回测用 TRAIN_TIMERANGE，最终评估用 VAL_TIMERANGE
- **Agent 只看到 val_score**：train_score 记录但不作为决策依据
- **交易次数阈值**：低于 MIN_TRADES 的策略直接判负
- **可选**：保留一个 holdout period，定期人工检查

---

## 5. 与 autoresearch 的设计对比

| 维度 | autoresearch | autoftresearch |
|------|-------------|----------------|
| 被修改的文件 | `train.py`（模型+训练） | `strategy.py`（策略逻辑） |
| 评估方式 | 直接训练 5 分钟 | hyperopt + backtest |
| Agent 角色 | 架构师 + 调参师 | 仅架构师（调参交给 hyperopt） |
| 时间预算 | 固定 5 分钟 | hyperopt epochs 固定（时间因机器而异） |
| 评估指标 | val_bpb（单一，越低越好） | 综合评分（Sharpe×收益×回撤，越高越好） |
| 过拟合防护 | 验证集 | Train/Val 时间分割 |
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
- [ ] 实现 Train/Val 时间分割
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
