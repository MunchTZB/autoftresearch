# autoftresearch

Autonomous quantitative strategy research, powered by AI agents and [freqtrade](https://www.freqtrade.io/).

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch): give an AI agent a real trading strategy framework and let it experiment autonomously. It modifies the strategy, runs hyperopt to optimize parameters, backtests on held-out data, checks if the result improved, keeps or discards, and repeats.

## How it works

The repo has three files that matter:

- **`prepare.py`** — fixed infrastructure: data download, hyperopt runner, backtest runner, scoring function. Not modified by the agent.
- **`strategy.py`** — the single file the agent edits. Contains a freqtrade `IStrategy` subclass with indicators, entry/exit signals, and hyperopt parameter search spaces. **This file is edited and iterated on by the agent.**
- **`program.md`** — instructions for the agent. Defines the research process, constraints, and evaluation criteria. **This file is edited and iterated on by the human.**

### The pipeline

For each experiment:

1. Agent modifies `strategy.py` (structural changes: indicators, signal logic, mechanisms)
2. `prepare.py` runs **hyperopt** on the training period (2022–2024) to find optimal parameters
3. `prepare.py` runs **backtest** on the test period (2024–2025) with those parameters
4. Results are scored and compared — keep or discard

The agent decides *what* to trade (strategy architecture). Hyperopt decides *how* (parameter values). This separation ensures the agent does real strategy research, not manual parameter search.

## Quick start

**Requirements:** Python 3.11+, uv.

```bash
# 1. Install uv (if needed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Install dependencies
uv sync

# 3. Download historical data (one-time, needs internet)
uv run prepare.py download

# 4. Run a single evaluation (hyperopt + backtest)
uv run prepare.py evaluate
```

## Running the agent

Spin up your AI agent (Claude, Codex, etc.) in this repo, then prompt:

```
Hi, have a look at program.md and let's kick off a new experiment! Let's do the setup first.
```

The agent will create a branch, establish a baseline, and start iterating autonomously.

## Project structure

```
prepare.py      — data download, hyperopt, backtest, scoring (do not modify)
strategy.py     — strategy logic with hyperopt spaces (agent modifies this)
program.md      — agent instructions
config.json     — freqtrade configuration (pairs, exchange)
pyproject.toml  — dependencies
PLAN.md         — project design document
```

## Design choices

- **Strategy vs parameters.** The agent only makes structural decisions (which indicators, what signal logic). Hyperopt handles parameter optimization. This prevents the agent from degenerating into a bad hyperopt.
- **Train/test split.** Hyperopt uses 2022–2024 data. Evaluation backtests on 2024–2025 data. The agent only sees test set results, preventing overfitting to training data.
- **Single file to modify.** The agent only touches `strategy.py`. This keeps scope manageable and diffs reviewable.
- **Self-contained.** One config, one strategy file, one evaluation script. No complex multi-file setups.

## License

MIT
