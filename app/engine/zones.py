"""Demand / Supply zone detection and validation.

Formation (user's rules, 2026-10-13):
  1st candle (leg-in)   any colour, TR >= ATR
  UOC group (base)      1-4 consecutive candles with TR < ATR, any colour
  3rd candle (leg-out)  TR >= ATR; green = demand, red = supply; must GAP away from the
                        last UOC: opens above its body top (demand) / below its body bottom (supply)
  Patterns: Demand DBR (Drop-Base-Rally), RBR (Rally-Base-Rally)
            Supply RBD (Rally-Base-Drop), DBD (Drop-Base-Drop)
  1-2-4 height rule     NOT required, but only zones that meet it can be grade A (best category):
                        with the tallest UOC candle = 1 (height = high - low), the 1st candle is
                        >= 2x and the 3rd candle >= 4x that height (ZONE_LEGIN_RATIO / ZONE_LEGOUT_RATIO)
  Fresh = price has not come back to the proximal line yet; Tested = it has (shown gray).

Lines (only the UOC candles between leg-in and leg-out are used):
  Demand  proximal (entry)     = highest high of the UOC candles + entry margin
          distal   (stop loss) = lowest low of the UOC candles - SL margin
  Supply  proximal (entry)     = lowest low of the UOC candles - entry margin
          distal   (stop loss) = highest high of the UOC candles + SL margin
  margins = ZONE_ENTRY_MARGIN_ATR / ZONE_SL_MARGIN_ATR x ATR of the last UOC candle

Validation (score out of 14):
  No. of UOC candles      1 = Great(3)  2 = Good(2)  3-4 = So-so(1)  >4 = Garbage(0)
  1-2-4 heights           base = 1, leg-in >= 2x tallest UOC = 2, leg-out >= 4x tallest UOC = 4
                          grade A only when both height checks pass
  Fresh vs Tested         fresh = 2, tested once = 1, more = 0      (White area / clean)
  Leg-out gap             leg-out body opens beyond base body = 1   (Gap is an opportunity)
  Leg-out body > wick     = 1
"""
from dataclasses import asdict, dataclass, field

import pandas as pd

from .. import config
from .indicators import add_indicators

BORING_GRADE = {1: ("Great", 3), 2: ("Good", 2), 3: ("So-so", 1), 4: ("So-so", 1)}
MAX_SCORE = 14


@dataclass
class Zone:
    kind: str                 # "demand" | "supply"
    pattern: str              # DBR | RBR | RBD | DBD
    tf: str
    legin_time: pd.Timestamp
    base_start: pd.Timestamp
    base_end: pd.Timestamp
    legout_time: pd.Timestamp
    proximal: float
    distal: float
    boring_count: int
    boring_grade: str
    base_uoc: bool            # all base candles TR < ATR
    legin_filled: bool        # 1-2-4: leg-in height >= 2x tallest UOC
    legout_filled: bool       # 1-2-4: leg-out height >= 4x tallest UOC
    legout_gap: bool
    legout_body_gt_wick: bool
    tests: int = 0            # times price came back to proximal
    first_test_time: pd.Timestamp | None = None
    broken: bool = False      # a candle closed beyond distal
    broken_time: pd.Timestamp | None = None
    score: int = 0
    grade: str = ""
    score_parts: dict = field(default_factory=dict)
    legin_x: float = 0.0      # leg-in height / tallest UOC height
    legout_x: float = 0.0     # leg-out height / tallest UOC height

    @property
    def fresh(self) -> bool:
        return self.tests == 0 and not self.broken

    @property
    def height(self) -> float:
        return abs(self.proximal - self.distal)

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, pd.Timestamp):
                d[k] = v.isoformat()
        d["fresh"] = self.fresh
        d["height"] = round(self.height, 2)
        d["proximal"] = round(self.proximal, 2)
        d["distal"] = round(self.distal, 2)
        return d


def _grade(score: int, rule_124: bool = True) -> str:
    if score >= 11 and rule_124:
        return "A"
    if score >= 11:
        return "B"
    if score >= 8:
        return "B"
    if score >= 5:
        return "C"
    return "D"


def find_zones(df: pd.DataFrame, tf: str = "", max_base: int | None = None,
               margin_atr: float | None = None, entry_margin_atr: float | None = None) -> list[Zone]:
    max_base = max_base or config.MAX_BASE_CANDLES
    margin_atr = config.ZONE_SL_MARGIN_ATR if margin_atr is None else margin_atr
    entry_margin_atr = config.ZONE_ENTRY_MARGIN_ATR if entry_margin_atr is None else entry_margin_atr
    d = df if "boring" in df.columns else add_indicators(df)
    if len(d) < 3:
        return []

    idx = d.index
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    green = d["green"].to_numpy()
    tr, atr = d["tr"].to_numpy(), d["atr"].to_numpy()
    uoc = tr < atr
    rng = d["range"].to_numpy()
    btop, bbot = d["body_top"].to_numpy(), d["body_bottom"].to_numpy()
    n = len(d)
    zones: list[Zone] = []

    i = 1
    while i < n - 1:
        # UOC group (TR < ATR) must start right after a leg-in candle (TR >= ATR)
        if not uoc[i] or uoc[i - 1]:
            i += 1
            continue
        j = i
        while j + 1 < n and uoc[j + 1]:
            j += 1
        legin, legout = i - 1, j + 1      # leg-out is the first candle after the group, so TR >= ATR
        count = j - i + 1
        # 3rd candle must have a colour (green = demand, red = supply)
        if legout >= n or count > max_base or c[legout] == o[legout]:
            i = j + 1
            continue

        base = slice(i, j + 1)
        demand = bool(c[legout] > o[legout])
        legin_up = bool(green[legin])

        margin, entry_margin = margin_atr * float(atr[j]), entry_margin_atr * float(atr[j])
        if demand:
            pattern = "RBR" if legin_up else "DBR"
            proximal = float(h[base].max()) + entry_margin
            distal = float(l[base].min()) - margin
            valid_move = c[legout] > proximal
            gap = o[legout] > btop[j]
        else:
            pattern = "DBD" if not legin_up else "RBD"
            proximal = float(l[base].min()) - entry_margin
            distal = float(h[base].max()) + margin
            valid_move = c[legout] < proximal
            gap = o[legout] < bbot[j]

        if not valid_move or not gap or proximal == distal:
            i = j + 1
            continue

        grade_name, boring_pts = BORING_GRADE.get(count, ("Garbage", 0))
        base_uoc = bool((tr[base] < atr[base]).all())
        # 1-2-4 heights (high - low) against the tallest UOC candle
        uoc_h = float(rng[base].max()) or 1e-9
        legin_x, legout_x = float(rng[legin]) / uoc_h, float(rng[legout]) / uoc_h
        legin_filled = legin_x >= config.ZONE_LEGIN_RATIO
        legout_filled = legout_x >= config.ZONE_LEGOUT_RATIO
        legout_body = abs(c[legout] - o[legout])
        body_gt_wick = bool(legout_body > (h[legout] - l[legout]) - legout_body)

        z = Zone(
            kind="demand" if demand else "supply", pattern=pattern, tf=tf,
            legin_time=idx[legin], base_start=idx[i], base_end=idx[j], legout_time=idx[legout],
            proximal=proximal, distal=distal, boring_count=count, boring_grade=grade_name,
            base_uoc=base_uoc, legin_filled=legin_filled, legout_filled=legout_filled,
            legout_gap=bool(gap), legout_body_gt_wick=body_gt_wick,
        )
        _check_freshness(z, legout, l, h, c, idx)

        parts = {
            "boring_candles": boring_pts,
            "base_uoc": 1 if base_uoc else 0,
            "legin_filled": 2 if legin_filled else 0,
            "legout_filled": 4 if legout_filled else 0,
            "fresh": 2 if z.tests == 0 else (1 if z.tests == 1 else 0),
            "gap": 1 if z.legout_gap else 0,
            "body_gt_wick": 1 if body_gt_wick else 0,
        }
        z.score_parts = parts
        z.score = sum(parts.values())
        z.legin_x, z.legout_x = round(legin_x, 2), round(legout_x, 2)
        z.grade = _grade(z.score, legin_filled and legout_filled)
        zones.append(z)
        i = j + 1

    return zones


def _check_freshness(z: Zone, legout: int, l, h, c, idx) -> None:
    """Count returns to the proximal line after the leg-out and detect a break of the distal."""
    inside = False
    for k in range(legout + 1, len(c)):
        if z.kind == "demand":
            touched = l[k] <= z.proximal
            broke = c[k] < z.distal
        else:
            touched = h[k] >= z.proximal
            broke = c[k] > z.distal
        if touched and not inside:
            z.tests += 1
            if z.first_test_time is None:
                z.first_test_time = idx[k]
        inside = touched
        if broke:
            z.broken = True
            z.broken_time = idx[k]
            return


def nearest_zones(zones: list[Zone], price: float) -> tuple[Zone | None, Zone | None]:
    """Nearest active demand zone at/below price and supply zone at/above price."""
    active = [z for z in zones if not z.broken]
    demand = [z for z in active if z.kind == "demand" and z.distal <= price]
    supply = [z for z in active if z.kind == "supply" and z.distal >= price]
    dz = max(demand, key=lambda z: (z.proximal, z.legout_time), default=None)
    sz = min(supply, key=lambda z: (z.proximal, -z.legout_time.value), default=None)
    return dz, sz


def curve_position(price: float, dz: Zone | None, sz: Zone | None) -> dict:
    """Divide the HTF curve (DZ proximal -> SZ proximal) into 3 parts."""
    if not dz or not sz or sz.proximal <= dz.proximal:
        return {"position": None, "label": "No curve"}
    pos = (price - dz.proximal) / (sz.proximal - dz.proximal)
    if price <= dz.proximal:
        label = "In Demand Zone"
    elif price >= sz.proximal:
        label = "In Supply Zone"
    elif pos < 1 / 3:
        label = "Low on curve"
    elif pos > 2 / 3:
        label = "High on curve"
    else:
        label = "Equilibrium"
    return {"position": round(pos, 3), "label": label}
