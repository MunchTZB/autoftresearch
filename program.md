# autoftresearch

Autonomous quantitative strategy research using freqtrade.

## Setup

To set up a new experiment, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar25`). The branch `autoftresearch/<tag>` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoftresearch/<tag>` from current master.
3. **Read the in-scope files**: The repo is small. Read these files for full context:
   - `README.md` — repository context.
   - `prepare.py` — fixed constants, data download, hyperopt runner, backtest runner, scoring. **Do not modify.**
   - `strategy.py` — the file you modify. Technical indicators, entry/exit signals, hyperopt parameter spaces.
   - `config.json` — freqtrade configuration (pairs, exchange, wallet). Do not modify.
4. **Verify data exists**: Check that `user_data/data/` contains candle data. If not, tell the human to run `uv run prepare.py download`.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment runs the full pipeline: hyperopt on training data → backtest on test data → score. You launch it as: `uv run prepare.py evaluate`.

**What you CAN do:**
- Modify `strategy.py` — this is the only file you edit. Everything is fair game: indicators, entry/exit logic, stoploss, trailing stop, timeframe, hyperopt parameter search spaces, custom callbacks.

**What you CANNOT do:**
- Modify `prepare.py`. It is read-only. It contains the fixed evaluation pipeline.
- Modify `config.json`. The pairs, exchange, and wallet settings are fixed.
- Install new packages or add dependencies. You can only use what's already in `pyproject.toml`.
- Modify the scoring function. `compute_score` in `prepare.py` is the ground truth metric.

**The goal is simple: get the highest test_score.** The score is computed from backtesting results on the TEST period (2024-01 to 2025-01), after hyperopt has optimized your strategy's parameters on the TRAIN period (2022-01 to 2024-01). Higher is better.

### What makes a good strategy

You are researching **strategy architecture**, not parameters. Hyperopt handles parameters. Your job is to decide:
- Which indicators to use and how to combine them
- What the entry/exit signal logic looks like
- What kind of stoploss/trailing mechanism to use
- What timeframe to trade on
- What the hyperopt search spaces should be (which parameters exist, their ranges)

A good strategy has:
- High Sharpe ratio on the test set
- Low maximum drawdown
- Reasonable number of trades (≥20 on test set)
- Simple, interpretable logic (not 15 stacked indicators)

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Removing something and getting equal or better results is a great outcome — that's a simplification win. A 0.001 test_score improvement from deleting code? Definitely keep. A huge block of complexity for marginal improvement? Probably not.

**The first run**: Your very first run should always be to establish the baseline, so you will run the pipeline on the strategy as is.

## Output format

The pipeline prints a summary like this:

```
---
test_score:         1.850000
test_sharpe:        1.9200
test_sortino:       2.1500
test_max_drawdown:  -0.1200
test_profit_pct:    35.20
test_trade_count:   87
test_win_rate:      0.6200
test_profit_factor: 1.8500
test_avg_profit:    0.4050
hyperopt_epochs:    500
hyperopt_loss:      SharpeHyperOptLossDaily
train_timerange:    20220101-20240101
test_timerange:     20240101-20250101
total_seconds:      423.5
```

You can extract the key metric:

```
grep "^test_score:" run.log
```

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated — commas break in descriptions).

The TSV has a header row and 6 columns:

```
commit	test_score	sharpe	max_dd_pct	status	description
```

1. git commit hash (short, 7 chars)
2. test_score (e.g. 1.234567) — use -999.000000 for crashes
3. sharpe ratio on test set (e.g. 1.92) — use 0.00 for crashes
4. max drawdown percent (e.g. 12.0 for -12%) — use 0.0 for crashes
5. status: `keep`, `discard`, or `crash`
6. short text description of what this experiment tried

Example:

```
commit	test_score	sharpe	max_dd_pct	status	description
a1b2c3d	0.850000	1.42	8.5	keep	baseline
b2c3d4e	1.230000	1.85	6.2	keep	replace RSI with MACD crossover + volume filter
c3d4e5f	0.650000	1.10	15.3	discard	add bollinger band squeeze — worse drawdown
d4e5f6g	-999.000000	0.00	0.0	crash	triple indicator stack caused hyperopt timeout
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoftresearch/mar25`).

LOOP FOREVER:

1. Look at the git state and review `results.tsv` for past experiments
2. Think about what structural change to try next (new indicators, different signal logic, different mechanism — NOT just tweaking a number)
3. Modify `strategy.py` with the experimental idea
4. git commit
5. Run the experiment: `uv run prepare.py evaluate > run.log 2>&1`
6. Read out the results: `grep "^test_score:\|^test_sharpe:\|^test_max_drawdown:\|^test_trade_count:" run.log`
7. If the grep output is empty, the run crashed. Run `tail -n 50 run.log` to read the error and attempt a fix. If you can't fix it after a few attempts, give up on this idea.
8. Record the results in `results.tsv` (NOTE: do not commit results.tsv, leave it untracked by git)
9. If test_score improved (higher), you "advance" the branch, keeping the git commit
10. If test_score is equal or worse, git reset back to where you started
11. Go to 1

**Timeout**: The evaluate pipeline typically takes 5-30 minutes depending on hardware. If it exceeds 60 minutes, kill it and treat it as a crash.

**Crashes**: If a run crashes, use your judgment. If it's a typo or import error, fix it and re-run. If the strategy idea itself is fundamentally broken, skip it, log "crash", and move on.

**NEVER STOP**: Once the experiment loop has begun, do NOT pause to ask the human. The human might be asleep. You are autonomous. If you run out of ideas, think harder — try combining previous near-misses, try radical structural changes, try different timeframes, try completely different indicator families. The loop runs until the human interrupts you, period.

## Strategy architecture ideas

When you run out of ideas, consider these directions:

- **Timeframe changes**: 15m, 1h, 4h — different timeframes expose different patterns
- **Indicator families**: trend (EMA, MACD, ADX), momentum (RSI, Stochastic, MFI), volatility (BB, ATR, Keltner), volume (OBV, VWAP, MFI)
- **Multi-indicator confirmation**: require 2-3 independent signals to agree
- **Regime detection**: use ADX or volatility to adapt behavior in trending vs ranging markets
- **Adaptive stoploss**: ATR-based dynamic stoploss instead of fixed percentage
- **Trailing mechanisms**: various trailing stop configurations
- **Time-based filters**: avoid trading during low-volume hours or specific days
- **Mean reversion vs trend following**: fundamentally different strategy philosophies
- **Breakout strategies**: Donchian channels, pivot points
- **Custom exit logic**: `custom_exit` callback for sophisticated exit conditions
