"""Walk-forward backtest of the swing plan in scanner.py.

The candles are replayed one LTF bar at a time and every decision uses only data that was
known at that moment:
  * Action (pulse + trend) comes from the last daily candle closed BEFORE the bar's day.
  * HTF curve uses weekly zones whose leg-out week has finished, and that were not broken
    in a finished week.
  * LTF zones are usable from the close of their leg-out candle; tests, breaks and the
    zone grade are counted only up to the current bar.

At each bar close with no open trade, the scanner rules pick a setup zone and place a limit
order at the proximal line (SL = distal, target = 1:RR). The order is re-evaluated at every
close (replaced or cancelled if the setup changes). Fills and exits are simulated
conservatively: if a bar touches both the stop and the target, the stop counts; a gap
through a level fills at the bar's open; an order is cancelled if the bar opens beyond the
stop. Each zone is traded at most once. Quantity = risk amount / risk per share, capped at
what the capital can buy.

CLI:  .venv\\Scripts\\python -m app.backtest [SYMBOL ...] [--ltf 2h] [--rr 5] [--min-grade C]
"""
import argparse
import math
from datetime import timedelta

import numpy as np
import pandas as pd

from . import config
from .data import get_candles, read_watchlist, resample_weekly
from .engine.indicators import add_indicators
from .engine.pulse_trend import ACTION_MATRIX
from .engine.zones import _grade, curve_position, find_zones
from .scanner import AGAINST_HTF

GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
WARMUP_BARS = 50          # LTF candles skipped so ATR / EMA have settled


def daily_actions(daily: pd.DataFrame) -> pd.DataFrame:
    """Action (side, text) for every daily candle, vectorised version of pulse() + trend()."""
    d = daily if "ema20" in daily.columns else add_indicators(daily)
    lb = config.TREND_LOOKBACK
    pulse = np.where(d["ema20"] > d["ema50"], "positive", "negative")
    atr = d["atr"].replace(0, 1e-9)
    angle = np.degrees(np.arctan((d["ema20"] - d["ema20"].shift(lb)) / (atr * lb) * 3))
    trend = np.select([angle > config.TREND_SIDEWAYS_DEG, angle < -config.TREND_SIDEWAYS_DEG],
                      ["uptrend", "downtrend"], "sideways")
    trend = np.where(angle.isna(), "unknown", trend)
    acts = [ACTION_MATRIX.get((p, t), ("NONE", "No action")) for p, t in zip(pulse, trend)]
    out = pd.DataFrame(acts, columns=["side", "text"], index=d.index.normalize())
    out.iloc[:50] = ("NONE", "No action")        # EMA 50 not settled yet
    return out


def _zone_events(z, start: int, l, h, c) -> tuple[list[int], int | None]:
    """Bar indices where price newly touched the proximal, and the bar that broke the distal."""
    tests, inside = [], False
    for k in range(start + 1, len(c)):
        if z.kind == "demand":
            touched, broke = l[k] <= z.proximal, c[k] < z.distal
        else:
            touched, broke = h[k] >= z.proximal, c[k] > z.distal
        if touched and not inside:
            tests.append(k)
        inside = touched
        if broke:
            return tests, k
    return tests, None


def _nearest(demand, supply, price):
    """Same choice as zones.nearest_zones, on zones already filtered to the active ones."""
    dz = max((z for z in demand if z.distal <= price), key=lambda z: (z.proximal, z.legout_time), default=None)
    sz = min((z for z in supply if z.distal >= price), key=lambda z: (z.proximal, -z.legout_time.value),
             default=None)
    return dz, sz


def _grade_at(z, tests: int) -> tuple[int, str]:
    fresh_pts = 2 if tests == 0 else (1 if tests == 1 else 0)
    score = z.score - z.score_parts["fresh"] + fresh_pts
    return score, _grade(score, z.legin_filled and z.legout_filled)


def run_symbol(symbol: str, ltf: str = "2h", reward_ratio: float | None = None,
               capital: float | None = None, risk_pct: float | None = None,
               min_grade: str = "D", sides: str = "both", aligned_only: bool = False,
               cost_pct: float = 0.0, refresh: bool = False, stop_buffer_atr: float = 0.0,
               close_stop: bool = False) -> dict:
    """close_stop=True: closing-basis stop loss - exit only when a candle CLOSES beyond the stop
    (at that close, so a loss can exceed 1R). Otherwise any touch of the stop exits at the stop."""
    rr = config.REWARD_RATIO if reward_ratio is None else reward_ratio
    capital = config.CAPITAL if capital is None else capital
    risk_pct = config.RISK_PCT if risk_pct is None else risk_pct
    min_rank = GRADE_RANK.get(min_grade.upper(), 1)
    allowed = {"both": ("BUY", "SELL"), "long": ("BUY",), "short": ("SELL",)}[sides]

    daily = add_indicators(get_candles(symbol, "D", refresh))
    weekly = add_indicators(resample_weekly(daily[["open", "high", "low", "close", "volume"]]))
    lower = add_indicators(get_candles(symbol, ltf, refresh, long_history=True))
    if len(lower) <= WARMUP_BARS + 1:
        raise ValueError(f"Not enough {ltf} candles for a backtest ({len(lower)})")

    acts = daily_actions(daily)
    act_dates = acts.index

    # Weekly zones with the time they became known / broken (a weekly candle is final a week later)
    week = timedelta(days=7)
    htf = [(z, z.legout_time + week, z.broken_time + week if z.broken else None)
           for z in find_zones(weekly, "W")]

    # LTF zones with their test / break bar indices
    idx = lower.index
    o, h, l, c = (lower[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr, tr = lower["atr"].to_numpy(), lower["tr"].to_numpy()
    ltf_zones, start_of = [], {}
    for z in find_zones(lower, ltf):
        start = idx.get_loc(z.legout_time)
        tests, broken = _zone_events(z, start, l, h, c)
        ltf_zones.append((z, start, tests, broken))
        start_of[id(z)] = start

    trades, pending, pos = [], None, None
    traded: set[int] = set()        # zones already used for a trade

    def close_trade(k, price, result):
        nonlocal pos
        d = 1 if pos["side"] == "BUY" else -1
        risk_ps = abs(pos["entry"] - pos["stoploss"])
        r = d * (price - pos["fill"]) / risk_ps
        cost_r = cost_pct / 100 * pos["fill"] / risk_ps
        qty = min(math.floor(capital * risk_pct / 100 / risk_ps), math.floor(capital / pos["fill"]))
        trades.append({
            **{k_: v for k_, v in pos.items() if k_ != "zone_id"}, "symbol": symbol, "exit_time": idx[k].isoformat(), "exit": round(price, 2),
            "result": result, "bars": k - pos["fill_bar"],
            "r": round(r, 3), "r_net": round(r - cost_r, 3), "qty": qty,
            "pnl": round(qty * d * (price - pos["fill"]) - cost_pct / 100 * pos["fill"] * qty, 2),
        })
        pos = None

    for k in range(WARMUP_BARS, len(lower)):
        # ---- 1. execute on this bar ----
        if pending and pos is None:
            p, E = pending, pending["entry"]
            fill = None
            S = p["stoploss"]
            if p["side"] == "BUY":
                fill = None if o[k] <= S else o[k] if o[k] <= E else (E if l[k] <= E else None)
            else:
                fill = None if o[k] >= S else o[k] if o[k] >= E else (E if h[k] >= E else None)
            if fill is not None:
                traded.add(p["zone_id"])
                pos = {**p, "fill": round(float(fill), 2), "fill_time": idx[k].isoformat(), "fill_bar": k}
                pending = None
                if close_stop:
                    if (c[k] < S) if pos["side"] == "BUY" else (c[k] > S):
                        close_trade(k, c[k], "stop")
                elif pos["side"] == "BUY" and l[k] <= S:          # stopped in the fill candle
                    close_trade(k, min(o[k], S), "stop")
                elif pos["side"] == "SELL" and h[k] >= S:
                    close_trade(k, max(o[k], S), "stop")
        elif pos is not None and close_stop:
            # target is a live order (wick fills it); the stop is checked only at the close
            S, T = pos["stoploss"], pos["target"]
            if pos["side"] == "BUY":
                if o[k] >= T:
                    close_trade(k, o[k], "target")
                elif h[k] >= T:
                    close_trade(k, T, "target")
                elif c[k] < S:
                    close_trade(k, c[k], "stop")
            else:
                if o[k] <= T:
                    close_trade(k, o[k], "target")
                elif l[k] <= T:
                    close_trade(k, T, "target")
                elif c[k] > S:
                    close_trade(k, c[k], "stop")
        elif pos is not None:
            S, T = pos["stoploss"], pos["target"]
            if pos["side"] == "BUY":
                if o[k] <= S:
                    close_trade(k, o[k], "stop")
                elif o[k] >= T:
                    close_trade(k, o[k], "target")
                elif l[k] <= S:
                    close_trade(k, S, "stop")
                elif h[k] >= T:
                    close_trade(k, T, "target")
            else:
                if o[k] >= S:
                    close_trade(k, o[k], "stop")
                elif o[k] <= T:
                    close_trade(k, o[k], "target")
                elif h[k] >= S:
                    close_trade(k, S, "stop")
                elif l[k] <= T:
                    close_trade(k, T, "target")

        if pos is not None:
            continue

        # ---- 2. decide at this bar's close (same rules as scanner.analyze) ----
        pending = None
        ts, price = idx[k], float(c[k])
        a = act_dates.searchsorted(ts.normalize(), side="left") - 1     # last daily candle before today
        if a < 0:
            continue
        side, act_text = acts.iloc[a]
        if side not in allowed:
            continue

        active = [(z, len([t for t in tests if t <= k])) for z, start, tests, broken in ltf_zones
                  if start <= k and (broken is None or broken > k)]
        tests_at = {id(z): n for z, n in active}
        dz, sz = _nearest([z for z, _ in active if z.kind == "demand"],
                          [z for z, _ in active if z.kind == "supply"], price)
        zone = dz if side == "BUY" else sz
        if zone is None or tests_at[id(zone)] > 1 or id(zone) in traded:
            continue
        score, grade = _grade_at(zone, tests_at[id(zone)])
        if GRADE_RANK[grade] < min_rank:
            continue

        h_active = [z for z, known, broken in htf if known <= ts and (broken is None or broken > ts)]
        hdz, hsz = _nearest([z for z in h_active if z.kind == "demand"],
                            [z for z in h_active if z.kind == "supply"], price)
        curve = curve_position(price, hdz, hsz)["label"]
        aligned = curve not in AGAINST_HTF[side]
        if aligned_only and not aligned:
            continue

        st = start_of[id(zone)]
        buf = stop_buffer_atr * atr[st] * (-1 if side == "BUY" else 1)
        entry, stop = round(zone.proximal, 2), round(zone.distal + buf, 2)
        if entry == stop:
            continue
        risk = abs(entry - stop)
        target = entry + rr * risk if side == "BUY" else entry - rr * risk
        height = abs(zone.proximal - zone.distal)
        if side == "BUY":
            departure = (h[st:k + 1].max() - zone.proximal) / height
            opp = sz.proximal if sz else None
            h_opp = hsz.proximal if hsz else None
        else:
            departure = (zone.proximal - l[st:k + 1].min()) / height
            opp = dz.proximal if dz else None
            h_opp = hdz.proximal if hdz else None
        room = lambda lvl: round(abs(lvl - entry) / risk, 2) if lvl is not None else None  # noqa: E731
        features = {
            "height_pct": round(height / zone.proximal * 100, 3), "height_atr": round(height / atr[st], 3),
            "legout_atr": round(tr[st] / atr[st], 3), "boring": zone.boring_count,
            "base_uoc": zone.base_uoc, "legin_filled": zone.legin_filled, "legout_filled": zone.legout_filled,
            "legin_x": zone.legin_x, "legout_x": zone.legout_x,
            "gap": zone.legout_gap, "body_gt_wick": zone.legout_body_gt_wick,
            "departure": round(float(departure), 2), "age": k - st,
            "dist_atr": round(abs(price - zone.proximal) / atr[k], 2),
            "room_ltf_r": room(opp), "room_htf_r": room(h_opp),
        }
        pending = {
            "zone_id": id(zone), "side": side, "pattern": zone.pattern, "grade": grade, "score": score,
            "tests": tests_at[id(zone)], "action": act_text, "curve": curve, "aligned": aligned,
            "zone_time": zone.legout_time.isoformat(), "signal_time": ts.isoformat(),
            "entry": entry, "stoploss": stop, "target": round(target, 2), **features,
        }

    if pos is not None:                                  # still running at the end of the data
        close_trade(len(lower) - 1, float(c[-1]), "open")

    return {
        "symbol": symbol, "ltf": ltf,
        "from": idx[WARMUP_BARS].isoformat(), "to": idx[-1].isoformat(), "bars": len(lower) - WARMUP_BARS,
        "trades": trades,
    }


def summarize(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["result"] != "open"]
    rs = [float(t["r_net"]) for t in sorted(closed, key=lambda t: t["exit_time"])]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    equity = np.cumsum(rs) if rs else np.array([0.0])
    drawdown = float((np.maximum.accumulate(np.maximum(equity, 0)) - equity).max())
    return {
        "trades": len(closed), "open": len(trades) - len(closed),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(100 * len(wins) / len(rs), 1) if rs else 0,
        "total_r": round(sum(rs), 2), "avg_r": round(sum(rs) / len(rs), 3) if rs else 0,
        "profit_factor": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) else None,
        "max_drawdown_r": round(drawdown, 2),
        "pnl": round(float(sum(t["pnl"] for t in closed)), 2),
    }


def main():
    ap = argparse.ArgumentParser(description="Backtest the demand/supply swing plan")
    ap.add_argument("symbols", nargs="*", help="NSE symbols (default: watchlist.txt)")
    ap.add_argument("--ltf", default="2h", choices=["2h", "1h"])
    ap.add_argument("--rr", type=float, default=None, help="reward ratio (default from .env)")
    ap.add_argument("--min-grade", default="D", choices=list("ABCD"))
    ap.add_argument("--sides", default="both", choices=["both", "long", "short"])
    ap.add_argument("--aligned", action="store_true", help="only trades aligned with the HTF curve")
    ap.add_argument("--cost", type=float, default=0.0, help="round-trip costs in %% of entry value")
    args = ap.parse_args()

    all_trades = []
    for sym in [s.upper() for s in args.symbols] or read_watchlist():
        try:
            res = run_symbol(sym, args.ltf, args.rr, min_grade=args.min_grade, sides=args.sides,
                             aligned_only=args.aligned, cost_pct=args.cost)
        except Exception as e:  # keep going on bad symbols
            print(f"{sym:12s} error: {e}")
            continue
        s = summarize(res["trades"])
        print(f"{sym:12s} trades {s['trades']:3d}  win {s['win_rate']:5.1f}%  total {s['total_r']:7.2f}R"
              f"  ({res['from'][:10]} -> {res['to'][:10]})")
        all_trades += res["trades"]
    print("\nOverall:", summarize(all_trades))


if __name__ == "__main__":
    main()
