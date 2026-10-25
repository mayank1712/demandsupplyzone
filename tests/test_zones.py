import pandas as pd

from app.engine.indicators import add_indicators
from app.engine.pulse_trend import action
from app.engine.risk import trade_plan
from app.engine.zones import find_zones


def make(candles):
    idx = pd.date_range("2025-01-01", periods=len(candles), freq="D")
    return pd.DataFrame(candles, columns=["open", "high", "low", "close"], index=idx).assign(volume=0)


# filler: small candles so ATR (~1.2) has history
FILL = [(100, 101, 99.5, 100.8), (100.8, 101.5, 100.5, 100.2)] * 8

# Drop-Base-Rally that follows the rules: leg-in TR >= ATR, 2 UOC (TR < ATR), green leg-out
# TR >= ATR that opens above the last UOC body (gap). Entry = UOC high 95.6, SL = UOC low 94.2 - margin
DBR = [
    (100, 100.5, 94, 94.5),     # 1st candle: big red, body > wick
    (94.5, 95.2, 94.2, 95.0),   # UOC
    (95.0, 95.6, 94.3, 94.8),   # UOC  -> highest high 95.6, last body top 95.0
    (95.2, 102, 95.0, 101.5),   # 3rd candle: big green, opens 95.2 > 95.0
    (101.5, 103, 101, 102.5),
]


def ours(zones, d, start=len(FILL)):
    """Zones formed by the test candles (ignore any formed inside the filler)."""
    return [z for z in zones if z.legin_time >= d.index[start]]


def flags(candles):
    d = add_indicators(make(candles))
    return d, (d["tr"] < d["atr"]).tolist()


def test_boring_definition():
    d = add_indicators(make([(100, 110, 90, 105), (100, 110, 90, 110), (92, 110, 90, 108)]))
    assert d["boring"].iloc[0]            # body 5 <= 50% of range 20
    assert d["boring"].iloc[1]            # body 10 == 50% -> still boring
    assert not d["boring"].iloc[2]        # body 16 > 50% -> exciting


def test_dbr_demand_zone():
    d, uoc = flags(FILL + DBR)
    n = len(FILL)
    assert not uoc[n] and uoc[n + 1] and uoc[n + 2] and not uoc[n + 3]   # preconditions
    zones = ours(find_zones(d, margin_atr=0, entry_margin_atr=0), d)
    assert len(zones) == 1
    z = zones[0]
    assert (z.kind, z.pattern) == ("demand", "DBR")
    assert z.proximal == 95.6         # highest high of the UOC candles
    assert z.distal == 94.2           # lowest low of the UOC candles (leg-in low 94 not used)
    assert z.boring_count == 2
    assert z.legout_gap and z.fresh and z.tests == 0
    assert z.legin_filled and z.legout_filled and z.grade == "A"     # 1-2-4: leg-in 5x, leg-out 5.4x


def test_leg_in_smaller_than_atr_is_not_a_zone():
    # user's case: 1st candle TR 6.70 < ATR 7.69 -> no zone
    big = [(100, 108, 99, 107), (107, 115, 106, 114)] * 8          # ATR ~8
    candles = big + [(114, 114.5, 108.0, 108.2)] + [               # 1st candle: TR 6.5 < ATR
        (108.2, 109, 107.5, 108.6),                                 # UOC
        (108.9, 118, 108.7, 117.5),                                 # big green, gap
    ]
    d, uoc = flags(candles)
    k = len(big)
    assert d["tr"].iloc[k] < d["atr"].iloc[k]
    assert [z for z in find_zones(d) if z.legout_time == d.index[k + 2]] == []


def test_more_than_four_uoc_is_not_a_zone():
    base = [(94.5, 95.0, 94.3, 94.8)] * 5                          # 5 UOC candles
    candles = FILL + [DBR[0]] + base + [(95.2, 102, 95.0, 101.5)]
    d, uoc = flags(candles)
    assert all(uoc[len(FILL) + 1:len(FILL) + 6])
    assert ours(find_zones(d), d) == []


def test_no_gap_is_not_a_zone():
    d = make(FILL + DBR[:3] + [(94.9, 102, 94.7, 101.5)])          # opens 94.9 < last UOC body 95.0
    assert ours(find_zones(d), d) == []


def test_uoc_colour_and_body_do_not_matter():
    # a UOC with a big body still counts, as long as TR < ATR
    candles = FILL + [DBR[0], (94.5, 95.4, 94.4, 95.3), (95.6, 102, 95.5, 101.5)]
    d, uoc = flags(candles)
    assert uoc[len(FILL) + 1] and not d["boring"].iloc[len(FILL) + 1]
    z = ours(find_zones(d, entry_margin_atr=0), d)[0]
    assert z.kind == "demand" and z.proximal == 95.4 and z.boring_count == 1


def test_rbd_supply_zone_tested_and_broken():
    candles = FILL + [
        (100, 106, 99.8, 105.5),    # 1st candle: big green
        (105.5, 106.2, 105.1, 105.8),   # UOC -> entry = low 105.1, SL = high 106.2
        (105.3, 105.6, 98, 98.5),   # 3rd candle: big red, opens below 105.5 (gap)
        (98.5, 106, 98, 104),       # comes back into zone (test)
        (104, 109, 103.5, 108.5),   # closes above distal -> broken
    ]
    d = make(candles)
    z = [z for z in ours(find_zones(d, margin_atr=0, entry_margin_atr=0), d) if z.pattern == "RBD"][0]
    assert z.kind == "supply"
    assert z.proximal == 105.1        # lowest low of the UOC candles
    assert z.distal == 106.2          # highest high of the UOC candles
    assert z.tests == 1 and not z.fresh
    assert z.broken


def test_action_matrix_and_plan():
    assert action("positive", "uptrend")["side"] == "BUY"
    assert action("negative", "uptrend")["side"] == "NONE"
    d = make(FILL + DBR)
    z = ours(find_zones(d, margin_atr=0, entry_margin_atr=0), d)[0]
    plan = trade_plan(z, capital=10000, risk_pct=0.5, reward_ratio=5)
    assert plan["entry"] == 95.6 and plan["stoploss"] == 94.2
    assert plan["target"] == 102.6           # 95.6 + 5 x 1.4
    assert plan["quantity"] == 35            # 50 / 1.4


def test_stop_loss_margin_is_fraction_of_atr():
    d = add_indicators(make(FILL + DBR))
    z = ours(find_zones(d, margin_atr=0.2), d)[0]
    atr_last_uoc = d["atr"].iloc[len(FILL) + 2]
    assert abs(z.distal - (94.2 - 0.2 * atr_last_uoc)) < 1e-9


def test_first_candle_needs_only_tr_above_atr():
    # OIL 17-Jul-2026 case: 1st candle has a tiny body but TR >= ATR -> still a zone
    candles = FILL + [(95.0, 100.5, 94, 94.8)] + DBR[1:]
    d, uoc = flags(candles)
    n = len(FILL)
    assert not uoc[n] and d["boring"].iloc[n]            # big range, small body
    z = ours(find_zones(d), d)[0]
    assert z.kind == "demand" and z.legin_time == d.index[n]


def test_entry_margin_is_above_uoc_high():
    d = add_indicators(make(FILL + DBR))
    z = ours(find_zones(d, margin_atr=0, entry_margin_atr=0.2), d)[0]
    assert abs(z.proximal - (95.6 + 0.2 * d["atr"].iloc[len(FILL) + 2])) < 1e-9


def test_124_rule_legout_below_4x_is_kept_but_not_grade_a():
    # APLAPOLLO 9-Oct-2026 case: leg-out passes TR >= ATR but is < 4x the UOC height
    candles = FILL + DBR[:3] + [(95.2, 99.0, 95.0, 98.8)]         # leg-out range 4.0 < 4 x 1.3
    d, uoc = flags(candles)
    n = len(FILL)
    assert not uoc[n + 3] and d["range"].iloc[n + 3] < 4 * d["range"].iloc[n + 1:n + 3].max()
    z = ours(find_zones(d), d)[0]
    assert z.legin_filled and not z.legout_filled
    assert z.grade != "A"


def test_124_rule_legin_below_2x_is_kept_but_not_grade_a():
    candles = FILL + [
        (100.2, 100.4, 98.0, 98.1),     # 1st candle: TR 2.4 >= ATR, but < 2 x 1.25
        (98.1, 98.9, 97.65, 98.5),      # UOC, height 1.25
        (98.9, 105, 98.8, 104.5),       # 3rd candle: big green with gap
    ]
    d, uoc = flags(candles)
    n = len(FILL)
    assert not uoc[n] and uoc[n + 1] and not uoc[n + 2]
    assert d["range"].iloc[n] < 2 * d["range"].iloc[n + 1]
    z = ours(find_zones(d), d)[0]
    assert not z.legin_filled and z.legout_filled
    assert z.grade != "A"
