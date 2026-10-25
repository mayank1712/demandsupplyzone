"""Weekly forward test ("journal").

Every week (Saturday, or with the button in the Journal tab):
  1. SAVE    every 2h zone formed in the last completed week (Mon-Fri), plus the scanner's trade setup
             at that week's close, with frozen entry / stop loss / 1:R target. Everything is computed from
             candles BEFORE the week ended, so nothing is known from the future.
  2. CHECK   every saved zone that is not finished: from the next week on, did price reach the entry,
             then the target or the stop? Two stop rules are tracked side by side:
               wick  - any touch of the stop exits at the stop
               close - closing-basis: exit only when a candle closes beyond the stop
             A zone that is not reached within JOURNAL_EXPIRY_WEEKS expires; an order is cancelled
             ("broken") if a candle opens beyond the stop before the entry was filled.
  3. REPORT  summary stats for the Journal tab and a CSV export.

Zones saved for weeks that had already finished more than a few days earlier are marked
`backfilled` (their outcome was not followed live).

CLI:  .venv\\Scripts\\python -m app.journal [--weeks N]
"""
import argparse
import csv
import io
import json
import sqlite3
import threading
from datetime import date, datetime, timedelta

import pandas as pd

from . import config
from .backtest import daily_actions
from .data import get_candles, read_watchlist, resample_weekly
from .engine.indicators import add_indicators
from .engine.zones import curve_position, find_zones, nearest_zones
from .scanner import AGAINST_HTF

TF = "2h"
FINAL = ("done", "broken", "expired")

COLUMNS = {
    "symbol": "TEXT", "tf": "TEXT", "kind": "TEXT", "pattern": "TEXT", "legout_time": "TEXT",
    "base_start": "TEXT", "found_week": "TEXT", "saved_at": "TEXT", "backfilled": "INTEGER",
    "is_new": "INTEGER", "is_setup": "INTEGER", "entry": "REAL", "stoploss": "REAL", "target": "REAL",
    "rr": "REAL", "grade": "TEXT", "score": "INTEGER", "uoc": "INTEGER", "legin_x": "REAL",
    "legout_x": "REAL", "rule_124": "INTEGER", "tests_at_save": "INTEGER", "action": "TEXT",
    "action_agrees": "INTEGER", "curve": "TEXT", "aligned": "INTEGER", "price_at_save": "REAL",
    "ref_close": "REAL", "settings": "TEXT", "status": "TEXT", "fill_time": "TEXT", "fill": "REAL",
    "wick_result": "TEXT", "wick_exit_time": "TEXT", "wick_exit": "REAL", "wick_r": "REAL",
    "close_result": "TEXT", "close_exit_time": "TEXT", "close_exit": "REAL", "close_r": "REAL",
    "end_time": "TEXT", "updated_at": "TEXT",
}

# progress of the current run (read by /api/journal/status)
JOB = {"running": False, "done": 0, "total": 0, "message": "", "error": None, "finished": None}
_lock = threading.Lock()


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.JOURNAL_FILE)
    conn.row_factory = sqlite3.Row
    cols = ", ".join(f"{k} {v}" for k, v in COLUMNS.items())
    conn.execute(f"CREATE TABLE IF NOT EXISTS zones (id INTEGER PRIMARY KEY, {cols}, "
                 "UNIQUE(symbol, tf, kind, legout_time))")
    conn.execute("CREATE TABLE IF NOT EXISTS weeks (week TEXT PRIMARY KEY, saved_at TEXT, zones INTEGER)")
    return conn


def last_completed_week(today: date | None = None) -> date:
    """Monday of the most recent Mon-Fri week that has finished."""
    today = today or date.today()
    wd = today.weekday()
    return today - timedelta(days=wd if wd >= 5 else wd + 7)


def weeks_to_save(conn, upto: date, weeks: int | None = None) -> list[date]:
    """Weeks not saved yet, up to `upto`. First run (or weeks=N): the last N weeks."""
    saved = {r["week"] for r in conn.execute("SELECT week FROM weeks")}
    if weeks:
        cands = [upto - timedelta(weeks=k) for k in range(weeks - 1, -1, -1)]
    elif saved:
        last = date.fromisoformat(max(saved))
        cands = [last + timedelta(weeks=k) for k in range(1, (upto - last).days // 7 + 1)]
    else:
        cands = [upto]
    return [w for w in cands if w.isoformat() not in saved]


def _settings() -> dict:
    return {k: getattr(config, k) for k in ("ZONE_SL_MARGIN_ATR", "ZONE_ENTRY_MARGIN_ATR", "ZONE_LEGIN_RATIO",
                                            "ZONE_LEGOUT_RATIO", "MAX_BASE_CANDLES", "ATR_PERIOD", "REWARD_RATIO")}


def snapshot_symbol(symbol: str, week: date, lower: pd.DataFrame, daily: pd.DataFrame) -> list[dict]:
    """Zones formed in `week` (+ the trade setup at the week's close), using only data before the week ended."""
    ws = pd.Timestamp(week)
    we = ws + pd.Timedelta(days=5)                      # Saturday 00:00
    lt = lower[lower.index < we]
    dt = daily[daily.index < we]
    if len(lt) < 60 or len(dt) < 60:
        return []
    zones = find_zones(lt, TF)
    price = float(lt["close"].iloc[-1])
    side, act_text = daily_actions(dt).iloc[-1]
    weekly = add_indicators(resample_weekly(dt[["open", "high", "low", "close", "volume"]]))
    hdz, hsz = nearest_zones(find_zones(weekly, "W"), price)
    curve = curve_position(price, hdz, hsz)["label"]
    dz, sz = nearest_zones(zones, price)
    setup = dz if side == "BUY" else sz if side == "SELL" else None
    if setup is not None and setup.tests > 1:
        setup = None

    picked = [z for z in zones if ws <= z.legout_time < we]
    if setup is not None and setup not in picked:
        picked.append(setup)
    rr = config.REWARD_RATIO
    now = datetime.now()
    backfilled = now > (we + pd.Timedelta(days=2, hours=9)).to_pydatetime()   # saved after next Monday 09:00
    rows = []
    for z in picked:
        zside = "BUY" if z.kind == "demand" else "SELL"
        entry, stop = round(z.proximal, 2), round(z.distal, 2)
        if entry == stop:
            continue
        target = entry + rr * abs(entry - stop) if zside == "BUY" else entry - rr * abs(entry - stop)
        rows.append({
            "symbol": symbol, "tf": TF, "kind": z.kind, "pattern": z.pattern,
            "legout_time": z.legout_time.isoformat(), "base_start": z.base_start.isoformat(),
            "found_week": week.isoformat(), "saved_at": now.isoformat(timespec="seconds"),
            "backfilled": int(backfilled), "is_new": int(ws <= z.legout_time < we), "is_setup": int(z is setup),
            "entry": entry, "stoploss": stop, "target": round(target, 2), "rr": rr,
            "grade": z.grade, "score": z.score, "uoc": z.boring_count, "legin_x": z.legin_x, "legout_x": z.legout_x,
            "rule_124": int(z.legin_filled and z.legout_filled), "tests_at_save": z.tests,
            "action": act_text, "action_agrees": int(side == zside), "curve": curve,
            "aligned": int(curve not in AGAINST_HTF[zside]), "price_at_save": round(price, 2),
            "ref_close": float(lower.loc[z.legout_time, "close"]), "settings": json.dumps(_settings()),
            "status": "waiting",
        })
    return rows


def simulate(lower: pd.DataFrame, kind: str, entry: float, stop: float, target: float,
             start: pd.Timestamp, expiry: pd.Timestamp, cost_pct: float) -> dict:
    """Follow one frozen zone from `start`: fill, then wick-stop and closing-stop outcomes."""
    seg = lower[lower.index >= start]
    sgn = 1 if kind == "demand" else -1
    # mirror supply into demand: prices *-1 (high and low swap)
    o, c = seg["open"].to_numpy() * sgn, seg["close"].to_numpy() * sgn
    h, l = (seg["high"], seg["low"]) if sgn == 1 else (-seg["low"], -seg["high"])
    h, l = h.to_numpy(), l.to_numpy()
    E, S, T = entry * sgn, stop * sgn, target * sgn
    risk = E - S
    idx = seg.index
    out = {"status": "waiting", "fill_time": None, "fill": None,
           "wick_result": None, "wick_exit_time": None, "wick_exit": None, "wick_r": None,
           "close_result": None, "close_exit_time": None, "close_exit": None, "close_r": None, "end_time": None}
    k0 = None
    for k in range(len(seg)):
        if idx[k] >= expiry:
            out.update(status="expired", end_time=idx[k].isoformat())
            return out
        if o[k] <= S:                                   # opened beyond the stop before filling
            out.update(status="broken", end_time=idx[k].isoformat())
            return out
        if l[k] <= E:
            k0, fill = k, min(o[k], E)
            break
    if k0 is None:
        return out
    cost_r = cost_pct / 100 * abs(fill) / risk
    out.update(status="filled", fill_time=idx[k0].isoformat(), fill=round(fill * sgn, 2))

    def finish(track, k, price, result):
        out.update({f"{track}_result": result, f"{track}_exit_time": idx[k].isoformat(),
                    f"{track}_exit": round(price * sgn, 2), f"{track}_r": round((price - fill) / risk - cost_r, 3)})

    wick_done = close_done = False
    if l[k0] <= S:                                      # stopped in the fill candle
        finish("wick", k0, min(o[k0], S), "stop"); wick_done = True
    if c[k0] < S:
        finish("close", k0, c[k0], "stop"); close_done = True
    for k in range(k0 + 1, len(seg)):
        if not wick_done:
            if o[k] <= S:
                finish("wick", k, o[k], "stop"); wick_done = True
            elif o[k] >= T:
                finish("wick", k, o[k], "target"); wick_done = True
            elif l[k] <= S:
                finish("wick", k, S, "stop"); wick_done = True
            elif h[k] >= T:
                finish("wick", k, T, "target"); wick_done = True
        if not close_done:
            if o[k] >= T:
                finish("close", k, o[k], "target"); close_done = True
            elif h[k] >= T:
                finish("close", k, T, "target"); close_done = True
            elif c[k] < S:
                finish("close", k, c[k], "stop"); close_done = True
        if wick_done and close_done:
            break
    for track, done in (("wick", wick_done), ("close", close_done)):
        if not done:
            out[f"{track}_result"] = "open"
            out[f"{track}_r"] = round((c[-1] - fill) / risk - cost_r, 3)     # unrealised, at the last close
    if wick_done and close_done:
        out.update(status="done", end_time=max(out["wick_exit_time"], out["close_exit_time"]))
    return out


def update_symbol(conn, symbol: str, lower: pd.DataFrame) -> int:
    """Re-check every unfinished zone of one stock. Returns the number of rows updated."""
    rows = conn.execute(f"SELECT * FROM zones WHERE symbol = ? AND status NOT IN {FINAL}", (symbol,)).fetchall()
    for r in rows:
        entry, stop, target, ref = r["entry"], r["stoploss"], r["target"], r["ref_close"]
        t = pd.Timestamp(r["legout_time"])
        if t in lower.index:                            # split / bonus: Yahoo re-adjusts old prices
            f = float(lower.loc[t, "close"]) / ref if ref else 1.0
            if abs(f - 1) > 0.02:
                entry, stop, target = (round(x * f, 2) for x in (entry, stop, target))
                ref = round(ref * f, 4)
        start = pd.Timestamp(r["found_week"]) + pd.Timedelta(days=7)                     # next Monday
        expiry = start + pd.Timedelta(weeks=config.JOURNAL_EXPIRY_WEEKS)
        res = simulate(lower, r["kind"], entry, stop, target, start, expiry, config.JOURNAL_COST_PCT)
        res.update(entry=entry, stoploss=stop, target=target, ref_close=ref,
                   updated_at=datetime.now().isoformat(timespec="seconds"))
        sets = ", ".join(f"{k} = ?" for k in res)
        conn.execute(f"UPDATE zones SET {sets} WHERE id = ?", (*res.values(), r["id"]))
    return len(rows)


def run(symbols: list[str] | None = None, weeks: int | None = None, today: date | None = None) -> dict:
    """Save missing weeks and update all unfinished zones. Thread-safe; used by the CLI, API and weekly.bat."""
    if not _lock.acquire(blocking=False):
        raise RuntimeError("A journal run is already in progress")
    try:
        symbols = symbols or read_watchlist()
        JOB.update(running=True, done=0, total=len(symbols), message="starting", error=None, finished=None)
        conn = connect()
        todo = weeks_to_save(conn, last_completed_week(today), weeks)
        saved, updated, errors = 0, 0, {}
        for n, sym in enumerate(symbols, 1):
            JOB.update(done=n - 1, message=sym)
            try:
                lower = add_indicators(get_candles(sym, TF, long_history=True))
                daily = add_indicators(get_candles(sym, "D"))
                for wk in todo:
                    for row in snapshot_symbol(sym, wk, lower, daily):
                        cols = ", ".join(row)
                        cur = conn.execute(f"INSERT OR IGNORE INTO zones ({cols}) VALUES ({', '.join('?' * len(row))})",
                                           tuple(row.values()))
                        if cur.rowcount:
                            saved += 1
                        elif row["is_setup"]:
                            conn.execute("UPDATE zones SET is_setup = 1 WHERE symbol = ? AND tf = ? AND kind = ? "
                                         "AND legout_time = ?", (sym, TF, row["kind"], row["legout_time"]))
                updated += update_symbol(conn, sym, lower)
                conn.commit()
            except Exception as e:  # keep going on bad symbols
                errors[sym] = str(e)
        now = datetime.now().isoformat(timespec="seconds")
        for wk in todo:
            n_w = conn.execute("SELECT COUNT(*) FROM zones WHERE found_week = ?", (wk.isoformat(),)).fetchone()[0]
            conn.execute("INSERT OR REPLACE INTO weeks VALUES (?, ?, ?)", (wk.isoformat(), now, n_w))
        conn.commit()
        conn.close()
        result = {"weeks_saved": [w.isoformat() for w in todo], "zones_saved": saved, "zones_checked": updated,
                  "errors": errors}
        JOB.update(done=len(symbols), message="finished", finished=now)
        return result
    except Exception as e:
        JOB.update(error=str(e))
        raise
    finally:
        JOB["running"] = False
        _lock.release()


def start_background(weeks: int | None = None) -> bool:
    if JOB["running"]:
        return False
    threading.Thread(target=lambda: _safe_run(weeks), daemon=True).start()
    return True


def _safe_run(weeks):
    try:
        run(weeks=weeks)
    except Exception:
        pass        # error is kept in JOB["error"]


def _stats(rows: list[dict], track: str) -> dict:
    closed = [r for r in rows if r[f"{track}_result"] in ("target", "stop")]
    rs = [r[f"{track}_r"] for r in closed]
    wins = [x for x in rs if x > 0]
    return {"trades": len(closed), "wins": len(wins), "win_rate": round(100 * len(wins) / len(rs), 1) if rs else None,
            "avg_r": round(sum(rs) / len(rs), 3) if rs else None, "total_r": round(sum(rs), 2),
            "running": sum(1 for r in rows if r[f"{track}_result"] == "open")}


def report(conn=None) -> dict:
    own = conn is None
    conn = conn or connect()
    rows = [dict(r) for r in conn.execute("SELECT * FROM zones ORDER BY found_week DESC, symbol")]
    weeks = [dict(r) for r in conn.execute("SELECT * FROM weeks ORDER BY week DESC")]
    if own:
        conn.close()
    groups = {
        "All zones": rows,
        "Trade setups": [r for r in rows if r["is_setup"]],
        "Grade A (1-2-4)": [r for r in rows if r["grade"] == "A"],
        "BUY + 1-2-4": [r for r in rows if r["kind"] == "demand" and r["rule_124"]],
        "Live only (not backfilled)": [r for r in rows if not r["backfilled"]],
    }
    status = {s: sum(1 for r in rows if r["status"] == s) for s in ("waiting", "filled", "done", "broken", "expired")}
    return {
        "zones": rows, "weeks": weeks, "status": status,
        "groups": [{"name": k, "zones": len(v), "wick": _stats(v, "wick"), "close": _stats(v, "close")}
                   for k, v in groups.items()],
        "settings": {"expiry_weeks": config.JOURNAL_EXPIRY_WEEKS, "cost_pct": config.JOURNAL_COST_PCT, "tf": TF},
        "job": dict(JOB),
    }


def export_csv() -> str:
    conn = connect()
    rows = conn.execute("SELECT * FROM zones ORDER BY found_week, symbol").fetchall()
    conn.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", *COLUMNS])
    for r in rows:
        w.writerow([r[k] for k in ["id", *COLUMNS]])
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description="Weekly zone journal: save last week's zones and check old ones")
    ap.add_argument("--weeks", type=int, default=None, help="(re)save the last N completed weeks (default: missing weeks)")
    ap.add_argument("symbols", nargs="*", help="NSE symbols (default: watchlist.txt)")
    args = ap.parse_args()
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] journal run ...", flush=True)
    res = run([s.upper() for s in args.symbols] or None, args.weeks)
    print(json.dumps(res, indent=1))
    for g in report()["groups"]:
        print(f"{g['name']:28s} zones {g['zones']:5d} | wick {g['wick']} | close {g['close']}")


if __name__ == "__main__":
    main()
