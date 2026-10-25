"""Swing trader scan: HTF = Weekly, ITF = Daily (pulse & trend), LTF = 2h or 1h (entry zone).

Plan Your Trade:
  1. Pulse  (Daily EMA 20/50)          2. Trend (Daily 7th candle clock)
  3. Action (pulse + trend matrix)     4. HTF zone & curve position (Weekly)
  5. When/Where to enter: nearest fresh LTF zone in the direction of the action
  6. Risk vs Reward: entry, stoploss, target, quantity
"""
from . import config
from .data import get_candles
from .engine.indicators import add_indicators
from .engine.pulse_trend import action, pulse, trend
from .engine.risk import trade_plan
from .engine.zones import curve_position, find_zones, nearest_zones

# Curve rule: buy low on the HTF curve, sell high. Trades in these curve positions are flagged.
AGAINST_HTF = {"BUY": ("In Supply Zone", "High on curve"), "SELL": ("In Demand Zone", "Low on curve")}

def _zone_brief(z, price):
    if z is None:
        return None
    d = z.to_dict()
    d["distance_pct"] = round((price - z.proximal) / price * 100, 2)
    return d


def analyze(symbol: str, ltf: str = "2h", capital=None, risk_pct=None, reward_ratio=None,
            refresh: bool = False) -> dict:
    weekly = add_indicators(get_candles(symbol, "W", refresh))
    daily = add_indicators(get_candles(symbol, "D", refresh))
    lower = add_indicators(get_candles(symbol, ltf, refresh))

    price = float(lower["close"].iloc[-1])

    # HTF curve
    htf_zones = find_zones(weekly, "W")
    htf_dz, htf_sz = nearest_zones(htf_zones, price)
    curve = curve_position(price, htf_dz, htf_sz)

    # Pulse, Trend, Action on daily
    p = pulse(daily)
    t = trend(daily)
    act = action(p["state"], t["state"])

    # LTF entry zone in the direction of action
    ltf_zones = find_zones(lower, ltf)
    ltf_dz, ltf_sz = nearest_zones(ltf_zones, price)
    setup_zone = None
    if act["side"] == "BUY" and ltf_dz and ltf_dz.tests <= 1:
        setup_zone = ltf_dz
    elif act["side"] == "SELL" and ltf_sz and ltf_sz.tests <= 1:
        setup_zone = ltf_sz
    plan = trade_plan(setup_zone, capital, risk_pct, reward_ratio) if setup_zone else None

    act["htf_aligned"] = act["side"] != "NONE" and curve["label"] not in AGAINST_HTF.get(act["side"], ())

    w_close, w_atr = float(weekly["close"].iloc[-1]), float(weekly["atr"].iloc[-1])
    return {
        "symbol": symbol,
        "price": round(price, 2),
        "last_candle": lower.index[-1].isoformat(),
        "pulse": p,
        "trend": t,
        "action": act,
        "curve": curve,
        "htf_demand": _zone_brief(htf_dz, price),
        "htf_supply": _zone_brief(htf_sz, price),
        "ltf": ltf,
        "ltf_demand": _zone_brief(ltf_dz, price),
        "ltf_supply": _zone_brief(ltf_sz, price),
        "setup": _zone_brief(setup_zone, price),
        "plan": plan,
        # Quick zone finder: closing price -/+ ATR (weekly)
        "atr_levels": {
            "weekly_atr": round(w_atr, 2),
            "demand_hint": round(w_close - w_atr, 2),
            "supply_hint": round(w_close + w_atr, 2),
        },
    }


def chart_payload(symbol: str, tf: str, refresh: bool = False, max_candles: int = 500) -> dict:
    df = add_indicators(get_candles(symbol, tf, refresh))
    zones = find_zones(df, tf)
    df = df.iloc[-max_candles:]
    start = df.index[0]
    shown = [z for z in zones if z.legout_time >= start and (not z.broken or z.broken_time >= start)]
    # lightweight-charts shows UTC; shift IST timestamps so the axis reads IST
    to_ts = lambda t: int(t.timestamp())  # noqa: E731  (index is naive IST already)
    candles = [
        {"time": to_ts(t), "open": r.open, "high": r.high, "low": r.low, "close": r.close,
         "tr": round(r.tr, 2), "atr": round(r.atr, 2)}
        for t, r in df.iterrows()
    ]
    return {
        "symbol": symbol,
        "tf": tf,
        "candles": candles,
        "ema20": [{"time": to_ts(t), "value": round(v, 2)} for t, v in df["ema20"].items()],
        "ema50": [{"time": to_ts(t), "value": round(v, 2)} for t, v in df["ema50"].items()],
        "zones": [dict(z.to_dict(), start_ts=to_ts(max(z.base_start, start)),
                       end_ts=to_ts(z.broken_time) if z.broken else to_ts(df.index[-1]))
                  for z in shown],
        "settings": {"capital": config.CAPITAL, "risk_pct": config.RISK_PCT,
                     "reward_ratio": config.REWARD_RATIO},
    }
