#!/usr/bin/env python3
"""
prepare.py — Fixed evaluation infrastructure for autoftresearch.

DO NOT MODIFY THIS FILE. The AI agent must not touch it.

Provides three subcommands:
    uv run prepare.py download   — Download historical K-line data
    uv run prepare.py evaluate   — Run hyperopt (train) → backtest (test) → score
    uv run prepare.py score-only — Re-score an existing backtest result (no re-run)

The evaluate pipeline:
    1. Sync strategy.py → user_data/strategies/AutoStrategy.py
    2. Hyperopt on TRAIN_TIMERANGE → exports best params to AutoStrategy.json
    3. Backtest on TEST_TIMERANGE using those params → parse results
    4. Compute and print test_score
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ============================================================
# Fixed constants — do not modify
# ============================================================
TRAIN_TIMERANGE = "20220101-20240101"
TEST_TIMERANGE = "20240101-20250101"
DOWNLOAD_TIMERANGE = "20220101-20250101"

HYPEROPT_EPOCHS = 500
HYPEROPT_LOSS = "SharpeHyperOptLossDaily"
HYPEROPT_SPACES = ["buy", "sell", "roi", "stoploss"]
HYPEROPT_MIN_TRADES = 10

MIN_TRADES = 20  # minimum trades on test set for a valid strategy

STRATEGY_NAME = "AutoStrategy"
CONFIG_FILE = "config.json"
USER_DATA_DIR = "user_data"
STRATEGY_DIR = os.path.join(USER_DATA_DIR, "strategies")
STRATEGY_SRC = "strategy.py"
STRATEGY_DST = os.path.join(STRATEGY_DIR, f"{STRATEGY_NAME}.py")
STRATEGY_PARAMS_FILE = os.path.join(STRATEGY_DIR, f"{STRATEGY_NAME}.json")

TIMEFRAME = "1h"
EXCHANGE = "binance"


# ============================================================
# Helpers
# ============================================================


def run_cmd(cmd: list[str], description: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    """Run a shell command, print description, return result."""
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{'='*60}\n")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        print(f"STDOUT:\n{result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout}")
        print(f"STDERR:\n{result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr}")
    return result


def ensure_dirs():
    """Create user_data directory structure if missing."""
    for d in [USER_DATA_DIR, STRATEGY_DIR, os.path.join(USER_DATA_DIR, "data"),
              os.path.join(USER_DATA_DIR, "hyperopt_results")]:
        os.makedirs(d, exist_ok=True)


def sync_strategy():
    """Copy strategy.py to user_data/strategies/AutoStrategy.py"""
    ensure_dirs()
    shutil.copy2(STRATEGY_SRC, STRATEGY_DST)
    print(f"Synced {STRATEGY_SRC} → {STRATEGY_DST}")

    # Remove stale params file so hyperopt starts fresh
    if os.path.exists(STRATEGY_PARAMS_FILE):
        os.remove(STRATEGY_PARAMS_FILE)
        print(f"Removed stale {STRATEGY_PARAMS_FILE}")


# ============================================================
# Download
# ============================================================


def download_data():
    """Download historical candle data for all configured pairs."""
    ensure_dirs()

    # Read pairs from config
    with open(CONFIG_FILE) as f:
        config = json.load(f)
    pairs = config.get("exchange", {}).get("pair_whitelist", [])

    if not pairs:
        print("ERROR: No pairs found in config.json pair_whitelist")
        sys.exit(1)

    cmd = [
        "freqtrade", "download-data",
        "--config", CONFIG_FILE,
        "--userdir", USER_DATA_DIR,
        "--timerange", DOWNLOAD_TIMERANGE,
        "--timeframe", TIMEFRAME,
        "--exchange", EXCHANGE,
        "-p", *pairs,
    ]
    result = run_cmd(cmd, f"Downloading data for {len(pairs)} pairs ({DOWNLOAD_TIMERANGE})")
    if result.returncode != 0:
        print("ERROR: Data download failed.")
        sys.exit(1)
    print("Data download complete.")


# ============================================================
# Hyperopt
# ============================================================


def run_hyperopt() -> bool:
    """
    Run hyperopt on TRAIN_TIMERANGE.
    Returns True if hyperopt completed successfully and exported params.
    """
    cmd = [
        "freqtrade", "hyperopt",
        "--config", CONFIG_FILE,
        "--userdir", USER_DATA_DIR,
        "--strategy", STRATEGY_NAME,
        "--strategy-path", STRATEGY_DIR,
        "--timerange", TRAIN_TIMERANGE,
        "--timeframe", TIMEFRAME,
        "--epochs", str(HYPEROPT_EPOCHS),
        "--spaces", *HYPEROPT_SPACES,
        "--hyperopt-loss", HYPEROPT_LOSS,
        "--min-trades", str(HYPEROPT_MIN_TRADES),
        "--no-color",
        "--print-json",
    ]
    result = run_cmd(cmd, f"Hyperopt: {HYPEROPT_EPOCHS} epochs on {TRAIN_TIMERANGE}")

    if result.returncode != 0:
        print("ERROR: Hyperopt failed.")
        print(result.stderr[-2000:] if result.stderr else "No stderr")
        return False

    # Hyperopt auto-exports params to STRATEGY_PARAMS_FILE
    if os.path.exists(STRATEGY_PARAMS_FILE):
        print(f"Hyperopt exported params to {STRATEGY_PARAMS_FILE}")
        with open(STRATEGY_PARAMS_FILE) as f:
            params = json.load(f)
        print(f"Best params: {json.dumps(params, indent=2)[:1000]}")
        return True

    print(f"WARNING: {STRATEGY_PARAMS_FILE} not found after hyperopt.")
    # Try to parse from stdout as fallback
    print("Hyperopt may have failed to find any valid result.")
    return False


# ============================================================
# Backtest
# ============================================================


def run_backtest() -> dict | None:
    """
    Run backtest on TEST_TIMERANGE using params from hyperopt.
    Returns parsed results dict or None on failure.
    """
    cmd = [
        "freqtrade", "backtesting",
        "--config", CONFIG_FILE,
        "--userdir", USER_DATA_DIR,
        "--strategy", STRATEGY_NAME,
        "--strategy-path", STRATEGY_DIR,
        "--timerange", TEST_TIMERANGE,
        "--timeframe", TIMEFRAME,
        "--no-header",
        "--export", "trades",
    ]
    result = run_cmd(cmd, f"Backtest: {TEST_TIMERANGE} with optimized params")

    if result.returncode != 0:
        print("ERROR: Backtest failed.")
        return None

    return parse_backtest_results(result.stdout)


def parse_backtest_results(stdout: str) -> dict | None:
    """Parse key metrics from freqtrade backtest stdout output."""
    results = {}
    output = stdout

    # Try to load from the exported JSON results
    bt_results_dir = Path(USER_DATA_DIR) / "backtest_results"
    if bt_results_dir.exists():
        json_files = sorted(bt_results_dir.glob("backtest-result-*.json"), reverse=True)
        if json_files:
            try:
                with open(json_files[0]) as f:
                    data = json.load(f)
                # Navigate the backtest result JSON structure
                strategy_data = data.get("strategy", {}).get(STRATEGY_NAME, {})
                if not strategy_data:
                    # Try alternative key formats
                    for key in data.get("strategy", {}):
                        strategy_data = data["strategy"][key]
                        break

                if strategy_data:
                    results["profit_total_pct"] = strategy_data.get("profit_total", 0) * 100
                    results["profit_factor"] = strategy_data.get("profit_factor", 0)
                    results["trade_count"] = strategy_data.get("trade_count", 0)
                    results["sharpe_ratio"] = strategy_data.get("sharpe", 0)
                    results["sortino_ratio"] = strategy_data.get("sortino", 0)
                    results["max_drawdown"] = strategy_data.get("max_drawdown", 0)
                    results["max_drawdown_pct"] = strategy_data.get("max_drawdown_account", 0)
                    results["avg_profit_pct"] = strategy_data.get("profit_mean", 0) * 100
                    results["win_rate"] = (
                        strategy_data.get("wins", 0) / strategy_data.get("trade_count", 1)
                        if strategy_data.get("trade_count", 0) > 0 else 0
                    )
                    results["holding_avg"] = strategy_data.get("holding_avg", "N/A")
                    return results
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"WARNING: Failed to parse backtest JSON: {e}")

    # Fallback: parse stdout with regex
    patterns = {
        "profit_total_pct": r"Total profit\s+.*?(\-?[\d.]+)%",
        "trade_count": r"Total/Daily Avg Trades\s+(\d+)",
        "sharpe_ratio": r"Sharpe\s+([\d.\-]+)",
        "sortino_ratio": r"Sortino\s+([\d.\-]+)",
        "max_drawdown_pct": r"Max Drawdown.*?(\d+\.\d+)%",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            try:
                results[key] = float(match.group(1))
            except ValueError:
                pass

    # Ensure trade_count is int
    if "trade_count" in results:
        results["trade_count"] = int(results["trade_count"])

    if not results:
        print("WARNING: Could not parse any results from backtest output.")
        print(f"Backtest stdout (last 2000 chars):\n{output[-2000:]}")
        return None

    # Normalize max_drawdown to negative fraction
    if "max_drawdown_pct" in results and results["max_drawdown_pct"] > 0:
        results["max_drawdown"] = -results["max_drawdown_pct"] / 100
    elif "max_drawdown" not in results:
        results["max_drawdown"] = 0

    if "sharpe_ratio" not in results:
        results["sharpe_ratio"] = 0
    if "profit_total_pct" not in results:
        results["profit_total_pct"] = 0

    return results


# ============================================================
# Scoring
# ============================================================


def compute_score(results: dict) -> float:
    """
    Compute a composite score from backtest results.
    Higher is better.
    """
    trade_count = results.get("trade_count", 0)
    sharpe = results.get("sharpe_ratio", 0)
    max_dd = results.get("max_drawdown", 0)  # negative, e.g. -0.12
    profit_pct = results.get("profit_total_pct", 0)

    if trade_count < MIN_TRADES:
        return -999.0

    # Sharpe-based score, penalized by drawdown
    # max_dd is negative, so (1 + max_dd) < 1 when there's drawdown
    score = sharpe * (1 + profit_pct / 100) * (1 + max_dd)
    return round(score, 6)


def print_results(results: dict, score: float, elapsed: float):
    """Print results in autoresearch-compatible format."""
    print("\n---")
    print(f"test_score:         {score:.6f}")
    print(f"test_sharpe:        {results.get('sharpe_ratio', 0):.4f}")
    print(f"test_sortino:       {results.get('sortino_ratio', 0):.4f}")
    print(f"test_max_drawdown:  {results.get('max_drawdown', 0):.4f}")
    print(f"test_profit_pct:    {results.get('profit_total_pct', 0):.2f}")
    print(f"test_trade_count:   {results.get('trade_count', 0)}")
    print(f"test_win_rate:      {results.get('win_rate', 0):.4f}")
    print(f"test_profit_factor: {results.get('profit_factor', 0):.4f}")
    print(f"test_avg_profit:    {results.get('avg_profit_pct', 0):.4f}")
    print(f"hyperopt_epochs:    {HYPEROPT_EPOCHS}")
    print(f"hyperopt_loss:      {HYPEROPT_LOSS}")
    print(f"train_timerange:    {TRAIN_TIMERANGE}")
    print(f"test_timerange:     {TEST_TIMERANGE}")
    print(f"total_seconds:      {elapsed:.1f}")


# ============================================================
# Main commands
# ============================================================


def cmd_download():
    """Subcommand: download historical data."""
    download_data()


def cmd_evaluate():
    """Subcommand: full evaluate pipeline (hyperopt → backtest → score)."""
    t0 = time.time()

    # Step 0: Sync strategy
    sync_strategy()

    # Step 1: Hyperopt on training set
    print("\n" + "=" * 60)
    print("  STEP 1: Hyperopt on training set")
    print("=" * 60)
    ok = run_hyperopt()
    if not ok:
        elapsed = time.time() - t0
        print("\n---")
        print(f"test_score:         -999.000000")
        print(f"status:             crash")
        print(f"reason:             hyperopt_failed")
        print(f"total_seconds:      {elapsed:.1f}")
        sys.exit(1)

    # Step 2: Backtest on test set
    print("\n" + "=" * 60)
    print("  STEP 2: Backtest on test set")
    print("=" * 60)
    results = run_backtest()
    if results is None:
        elapsed = time.time() - t0
        print("\n---")
        print(f"test_score:         -999.000000")
        print(f"status:             crash")
        print(f"reason:             backtest_failed")
        print(f"total_seconds:      {elapsed:.1f}")
        sys.exit(1)

    # Step 3: Score
    score = compute_score(results)
    elapsed = time.time() - t0
    print_results(results, score, elapsed)


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run prepare.py <command>")
        print("Commands:")
        print("  download   — Download historical K-line data")
        print("  evaluate   — Run hyperopt → backtest → score")
        sys.exit(1)

    command = sys.argv[1]
    if command == "download":
        cmd_download()
    elif command == "evaluate":
        cmd_evaluate()
    else:
        print(f"Unknown command: {command}")
        print("Available: download, evaluate")
        sys.exit(1)


if __name__ == "__main__":
    main()
