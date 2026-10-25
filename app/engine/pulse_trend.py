"""Pulse (EMA 20/50 crossover) and Trend (7th candle clock rule on EMA 20)."""
import math

import pandas as pd

from .. import config
from .indicators import add_indicators


def pulse(df: pd.DataFrame) -> dict:
    """Positive: EMA20 above EMA50. Signal is confirmed when a candle closes green after a
    positive crossover (red after a negative crossover)."""
    d = df if "ema20" in df.columns else add_indicators(df)
    diff = (d["ema20"] - d["ema50"]).to_numpy()
    state = "positive" if diff[-1] > 0 else "negative"

    since = None
    for k in range(len(diff) - 1, 0, -1):
        if (diff[k] > 0) != (diff[k - 1] > 0):
            since = len(diff) - 1 - k
            cross_idx = k
            break

    confirmed = False
    if since is not None:
        after = d["green"].iloc[cross_idx:]
        confirmed = bool(after.any()) if state == "positive" else bool((~after).any())
    return {
        "state": state,
        "candles_since_cross": since,
        "confirmed": confirmed,
        "ema20": round(float(d["ema20"].iloc[-1]), 2),
        "ema50": round(float(d["ema50"].iloc[-1]), 2),
    }


def trend(df: pd.DataFrame, lookback: int | None = None) -> dict:
    """Chart is a clock, EMA 20 is the needle. Measure the needle's angle over the last
    `lookback` closed candles (price change scaled by ATR so it works for any stock).
      12-3 o'clock -> Uptrend, around 3 -> Sideways, 3-6 -> Downtrend
    """
    lookback = lookback or config.TREND_LOOKBACK
    d = df if "ema20" in df.columns else add_indicators(df)
    if len(d) <= lookback:
        return {"state": "unknown", "angle": None, "clock": None}
    ema_now = float(d["ema20"].iloc[-1])
    ema_then = float(d["ema20"].iloc[-1 - lookback])
    atr = float(d["atr"].iloc[-1]) or 1e-9
    # EMA moving 1/3 ATR per candle ~ 45 degrees
    slope = (ema_now - ema_then) / (atr * lookback)
    angle = math.degrees(math.atan(slope * 3))
    clock = 3 - angle / 30                     # 90deg -> 12, 0deg -> 3, -90deg -> 6
    if angle > config.TREND_SIDEWAYS_DEG:
        state = "uptrend"
    elif angle < -config.TREND_SIDEWAYS_DEG:
        state = "downtrend"
    else:
        state = "sideways"
    return {"state": state, "angle": round(angle, 1), "clock": round(clock, 1)}


ACTION_MATRIX = {
    ("positive", "uptrend"): ("BUY", "Buy / Long"),
    ("positive", "sideways"): ("BUY", "Buy with conviction"),
    ("positive", "downtrend"): ("NONE", "No action"),
    ("negative", "downtrend"): ("SELL", "Sell / Short"),
    ("negative", "sideways"): ("SELL", "Short with conviction"),
    ("negative", "uptrend"): ("NONE", "No action"),
}


def action(pulse_state: str, trend_state: str) -> dict:
    side, text = ACTION_MATRIX.get((pulse_state, trend_state), ("NONE", "No action"))
    return {"side": side, "text": text}
