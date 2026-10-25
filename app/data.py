"""Candle loading with on-disk cache and timeframe resampling.

Timeframes:  W (weekly), D (daily), 2h, 1h
  W  <- resampled from daily (week starts Monday)
  2h <- resampled from 60 min, aligned to NSE session like TradingView: 09:15, 11:15, 13:15, 15:15
"""
import os
import time

import pandas as pd

from . import config
from .providers import get_provider

TIMEFRAMES = ("W", "D", "2h", "1h")
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def _cache_path(symbol: str, kind: str):
    return config.CACHE_DIR / f"{config.DATA_PROVIDER}_{symbol.upper()}_{kind}.csv"


def _load(symbol: str, kind: str, refresh: bool) -> pd.DataFrame:
    path = _cache_path(symbol, kind)
    ttl = config.INTRADAY_CACHE_MINUTES if kind == "60m" else config.DAILY_CACHE_MINUTES
    if not refresh and path.exists() and (time.time() - path.stat().st_mtime) < ttl * 60:
        return pd.read_csv(path, index_col=0, parse_dates=True)

    provider = get_provider()
    if kind == "daily":
        df = provider.daily(symbol, config.DAILY_HISTORY_DAYS)
    elif kind == "60m_long":   # backtest history
        df = provider.intraday(symbol, 60, config.BACKTEST_INTRADAY_DAYS)
    else:
        df = provider.intraday(symbol, 60, config.INTRADAY_HISTORY_DAYS)
    if df.empty:
        raise ValueError(f"No {kind} data returned for {symbol}")
    # write to a temp file first so a reader never sees a half-written cache file
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    df.to_csv(tmp)
    os.replace(tmp, path)
    return df


def resample_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    weeks = daily.index.to_period("W")
    w = daily.groupby(weeks).agg(AGG)
    w.index = w.index.start_time
    return w


def resample_2h(hourly: pd.DataFrame) -> pd.DataFrame:
    # offset 75min puts bin edges at ..., 09:15, 11:15, 13:15, 15:15
    return hourly.resample("120min", offset="75min").agg(AGG).dropna(subset=["open"])


def get_candles(symbol: str, tf: str, refresh: bool = False, long_history: bool = False) -> pd.DataFrame:
    if tf not in TIMEFRAMES:
        raise ValueError(f"Unknown timeframe {tf}")
    if tf in ("W", "D"):
        daily = _load(symbol, "daily", refresh)
        return resample_weekly(daily) if tf == "W" else daily
    hourly = _load(symbol, "60m_long" if long_history else "60m", refresh)
    return resample_2h(hourly) if tf == "2h" else hourly


def read_watchlist() -> list[str]:
    if not config.WATCHLIST_FILE.exists():
        return []
    out = []
    for line in config.WATCHLIST_FILE.read_text(encoding="utf-8").splitlines():
        s = line.split("#")[0].strip().upper()
        if s:
            out.append(s)
    return out
