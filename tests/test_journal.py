from datetime import date

import pandas as pd

from app import config, journal
from app.data import resample_2h
from app.engine.indicators import add_indicators
from test_backtest import synthetic


def bars(rows, start="2025-01-06 09:15"):
    idx = pd.date_range(start, periods=len(rows), freq="2h")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def sim(rows, kind="demand", E=100, S=98, T=110, expiry="2030-01-01"):
    return journal.simulate(bars(rows), kind, E, S, T, pd.Timestamp("2025-01-01"), pd.Timestamp(expiry), 0.0)


def test_target_after_fill():
    r = sim([(105, 106, 104, 105), (104, 104.5, 99.5, 101), (101, 111, 100.5, 110)])
    assert r["status"] == "done" and r["fill"] == 100
    assert r["wick_result"] == r["close_result"] == "target"
    assert r["wick_r"] == r["close_r"] == 5.0


def test_wick_stop_but_close_survives():
    # wick goes below the stop (97.5) but the candle closes above it (99) -> close rule keeps the trade
    r = sim([(105, 106, 104, 105), (104, 104.5, 99.5, 101), (101, 101.5, 97.5, 99), (99, 111, 98.5, 110)])
    assert r["wick_result"] == "stop" and r["wick_r"] == -1.0
    assert r["close_result"] == "target" and r["close_r"] == 5.0


def test_close_stop_exits_at_close():
    r = sim([(105, 106, 104, 105), (104, 104.5, 99.5, 101), (101, 101.5, 96, 97)])
    assert r["close_result"] == "stop" and r["close_exit"] == 97 and r["close_r"] == -1.5


def test_open_beyond_stop_before_fill_is_broken_and_untouched_expires():
    assert sim([(105, 106, 104, 105), (97, 99, 96, 98)])["status"] == "broken"
    assert sim([(105, 106, 104, 105)] * 20, expiry="2025-01-07")["status"] == "expired"
    assert sim([(105, 106, 104, 105)] * 3)["status"] == "waiting"


def test_supply_is_mirrored():
    r = sim([(95, 96, 94, 95), (96, 100.5, 95.5, 99), (99, 99.5, 89, 90)], kind="supply", E=100, S=102, T=90)
    assert r["fill"] == 100 and r["wick_result"] == "target" and r["wick_r"] == 5.0


def test_snapshot_uses_no_future_data():
    daily, hourly = synthetic()
    lower, d = add_indicators(resample_2h(hourly)), add_indicators(daily)
    strip = lambda rows: [{k: v for k, v in r.items() if k != "saved_at"} for r in rows]  # noqa: E731
    found = 0
    for k in range(12):
        week = date(2025, 3, 3) + pd.Timedelta(weeks=k)
        end = pd.Timestamp(week) + pd.Timedelta(days=5)
        full = journal.snapshot_symbol("T", week, lower, d)
        cut = journal.snapshot_symbol("T", week, add_indicators(resample_2h(hourly[hourly.index < end])),
                                      add_indicators(daily[daily.index < end]))
        assert strip(full) == strip(cut)
        found += len(full)
    assert found > 3


def test_run_saves_once_and_updates(monkeypatch, tmp_path):
    daily, hourly = synthetic()
    monkeypatch.setattr(config, "JOURNAL_FILE", tmp_path / "j.db")
    monkeypatch.setattr(journal, "get_candles",
                        lambda s, tf, refresh=False, long_history=False: daily if tf == "D" else resample_2h(hourly))
    today = date(2025, 6, 28)                                       # Saturday
    res = journal.run(["T"], weeks=4, today=today)
    assert res["weeks_saved"] == ["2025-06-02", "2025-06-09", "2025-06-16", "2025-06-23"]
    assert res["zones_saved"] > 0 and not res["errors"]
    again = journal.run(["T"], today=today)                         # nothing new to save
    assert again["weeks_saved"] == [] and again["zones_saved"] == 0
    rep = journal.report()
    assert len(rep["zones"]) == res["zones_saved"]
    assert {z["status"] for z in rep["zones"]} <= {"waiting", "filled", "done", "broken", "expired"}
    for z in rep["zones"]:
        if z["fill_time"]:
            assert z["fill_time"] >= "2025-06-09"                   # checking starts the week after saving
