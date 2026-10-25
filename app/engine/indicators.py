"""Candle anatomy and indicators used by the zone rules."""
import numpy as np
import pandas as pd

from .. import config


def add_indicators(df: pd.DataFrame, atr_period: int | None = None) -> pd.DataFrame:
    atr_period = atr_period or config.ATR_PERIOD
    d = df.copy()
    prev_close = d["close"].shift(1)

    # True Range and ATR (RMA smoothing, same as TradingView "ATR 14 RMA")
    d["tr"] = pd.concat([
        d["high"] - d["low"],
        (d["high"] - prev_close).abs(),
        (d["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    d["atr"] = d["tr"].ewm(alpha=1 / atr_period, adjust=False).mean()

    # Boring: body (open-close) <= 50% of range (high-low). Exciting: body > 50%.
    d["body"] = (d["close"] - d["open"]).abs()
    d["range"] = d["high"] - d["low"]
    d["boring"] = (d["body"] <= 0.5 * d["range"]) | (d["range"] == 0)
    d["green"] = d["close"] >= d["open"]
    d["body_top"] = np.maximum(d["open"], d["close"])
    d["body_bottom"] = np.minimum(d["open"], d["close"])

    # Pulse: EMA 20 / 50
    d["ema20"] = d["close"].ewm(span=20, adjust=False).mean()
    d["ema50"] = d["close"].ewm(span=50, adjust=False).mean()
    return d
