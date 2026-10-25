"""Risk vs Reward: quantity = risk amount / (entry - stoploss)."""
import math

from .. import config
from .zones import Zone


def trade_plan(zone: Zone, capital: float | None = None, risk_pct: float | None = None,
               reward_ratio: float | None = None) -> dict | None:
    capital = config.CAPITAL if capital is None else capital
    risk_pct = config.RISK_PCT if risk_pct is None else risk_pct
    rr = config.REWARD_RATIO if reward_ratio is None else reward_ratio

    entry, stop = zone.proximal, zone.distal
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return None
    target = entry + rr * risk_per_share if zone.kind == "demand" else entry - rr * risk_per_share
    risk_amount = capital * risk_pct / 100
    qty = math.floor(risk_amount / risk_per_share)
    return {
        "side": "BUY" if zone.kind == "demand" else "SELL",
        "entry": round(entry, 2),
        "stoploss": round(stop, 2),
        "target": round(target, 2),
        "risk_per_share": round(risk_per_share, 2),
        "risk_amount": round(risk_amount, 2),
        "quantity": qty,
        "actual_risk": round(qty * risk_per_share, 2),
        "reward": round(qty * risk_per_share * rr, 2),
        "capital_needed": round(qty * entry, 2),
        "rr": f"1:{rr:g}",
    }
