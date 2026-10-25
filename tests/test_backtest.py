import numpy as np
import pandas as pd

from app import backtest
from app.data import resample_2h
from app.engine.indicators import add_indicators
from app.engine.pulse_trend import action, pulse, trend


def random_walk(index, seed, start=100.0, vol=0.01):
    rng = np.random.default_rng(seed)
    close = start * np.exp(np.cumsum(rng.normal(0.0003, vol, len(index))))
    open_ = np.r_[start, close[:-1]] * np.exp(rng.normal(0, vol / 3, len(index)))
    spread = np.abs(rng.normal(0, vol, len(index))) * close
    return pd.DataFrame({
        "open": open_, "close": close,
        "high": np.maximum(open_, close) + spread, "low": np.minimum(open_, close) - spread,
        "volume": 1000.0,
    }, index=index)


def synthetic(seed=1):
    daily = random_walk(pd.bdate_range("2023-01-02", periods=950), seed, vol=0.015)
    days = pd.bdate_range("2024-06-03", periods=550)
    hours = pd.DatetimeIndex([d + pd.Timedelta(hours=9, minutes=15) + pd.Timedelta(hours=i)
                              for d in days for i in range(7)])
    hourly = random_walk(hours, seed + 1, start=float(daily["close"].iloc[-551]), vol=0.006)
    return daily, hourly


def patch_data(monkeypatch, daily, hourly):
    def fake(symbol, tf, refresh=False, long_history=False):
        return daily if tf == "D" else resample_2h(hourly) if tf == "2h" else hourly
    monkeypatch.setattr(backtest, "get_candles", fake)


def test_daily_actions_match_scanner_functions():
    daily = add_indicators(synthetic()[0])
    acts = backtest.daily_actions(daily)
    for k in range(60, len(daily), 37):
        d = daily.iloc[:k + 1]
        expected = action(pulse(d)["state"], trend(d)["state"])
        assert tuple(acts.iloc[k]) == (expected["side"], expected["text"])


def test_no_lookahead(monkeypatch):
    """Trades that finished before a cut-off must be identical with or without later data."""
    daily, hourly = synthetic()
    patch_data(monkeypatch, daily, hourly)
    full = backtest.run_symbol("TEST", "1h")["trades"]
    assert len(full) > 5

    cut = hourly.index[len(hourly) * 2 // 3]
    patch_data(monkeypatch, daily[daily.index < cut.normalize()], hourly[hourly.index < cut])
    part = backtest.run_symbol("TEST", "1h")["trades"]

    done = lambda ts: [t for t in ts if t["result"] != "open" and pd.Timestamp(t["exit_time"]) < cut - pd.Timedelta(days=7)]  # noqa: E731
    assert done(full) == done(part)


def test_trades_respect_plan(monkeypatch):
    daily, hourly = synthetic(seed=7)
    patch_data(monkeypatch, daily, hourly)
    trades = backtest.run_symbol("TEST", "2h", reward_ratio=3)["trades"]
    for t in trades:
        assert t["signal_time"] < t["fill_time"] <= t["exit_time"]
        if t["result"] == "target":
            assert (t["exit"] >= t["target"]) if t["side"] == "BUY" else (t["exit"] <= t["target"])
            assert abs(abs(t["target"] - t["entry"]) - 3 * abs(t["entry"] - t["stoploss"])) < 0.01
        if t["result"] == "stop":
            assert t["r"] <= 0
    zones = [t["zone_time"] + t["side"] for t in trades]
    assert len(zones) == len(set(zones))          # one trade per zone
