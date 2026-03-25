"""
AutoStrategy — the single file the AI agent modifies.

This is a freqtrade IStrategy subclass. The agent iterates on:
  - Which technical indicators to compute
  - Entry/exit signal logic and condition combinations
  - Stoploss / take-profit mechanisms (fixed, trailing, dynamic)
  - Hyperopt parameter search spaces (DecimalParameter, IntParameter, etc.)
  - Timeframe selection

The agent should NOT hardcode parameter values — use Parameter types so
hyperopt can optimize them.
"""

from functools import reduce

import pandas_ta as pta
from pandas import DataFrame

from freqtrade.strategy import (
    BooleanParameter,
    CategoricalParameter,
    DecimalParameter,
    IStrategy,
    IntParameter,
)


class AutoStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    # -- Stoploss / ROI (hyperopt will search these spaces) --
    stoploss = -0.10
    minimal_roi = {"0": 0.10, "30": 0.05, "60": 0.02, "120": 0}
    trailing_stop = False

    startup_candle_count: int = 200

    # -------------------------------------------------------
    # Hyperoptable parameters — agent defines the search space,
    # hyperopt finds the optimal values.
    # -------------------------------------------------------

    # RSI guard
    buy_rsi_enabled = BooleanParameter(default=True, space="buy")
    buy_rsi = IntParameter(10, 40, default=30, space="buy")

    # EMA trend filter
    buy_ema_enabled = BooleanParameter(default=True, space="buy")
    buy_ema_short = IntParameter(5, 30, default=10, space="buy")
    buy_ema_long = IntParameter(30, 200, default=50, space="buy")

    # Exit RSI
    sell_rsi_enabled = BooleanParameter(default=True, space="sell")
    sell_rsi = IntParameter(60, 90, default=70, space="sell")

    # ----- Indicators -----

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = pta.rsi(dataframe["close"], length=14)

        for val in self.buy_ema_short.range:
            dataframe[f"ema_short_{val}"] = pta.ema(dataframe["close"], length=val)

        for val in self.buy_ema_long.range:
            dataframe[f"ema_long_{val}"] = pta.ema(dataframe["close"], length=val)

        dataframe["volume_mean_20"] = dataframe["volume"].rolling(20).mean()

        return dataframe

    # ----- Entry -----

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        if self.buy_rsi_enabled.value:
            conditions.append(dataframe["rsi"] < self.buy_rsi.value)

        if self.buy_ema_enabled.value:
            ema_short_col = f"ema_short_{self.buy_ema_short.value}"
            ema_long_col = f"ema_long_{self.buy_ema_long.value}"
            if ema_short_col in dataframe.columns and ema_long_col in dataframe.columns:
                conditions.append(dataframe[ema_short_col] > dataframe[ema_long_col])

        conditions.append(dataframe["volume"] > dataframe["volume_mean_20"] * 0.5)
        conditions.append(dataframe["volume"] > 0)

        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "enter_long"] = 1

        return dataframe

    # ----- Exit -----

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        conditions = []

        if self.sell_rsi_enabled.value:
            conditions.append(dataframe["rsi"] > self.sell_rsi.value)

        conditions.append(dataframe["volume"] > 0)

        if conditions:
            dataframe.loc[reduce(lambda x, y: x & y, conditions), "exit_long"] = 1

        return dataframe
