# CLAUDE.md

Demand & Supply Zone Scanner for NSE stocks: a FastAPI backend + plain-JS web dashboard that applies the
"Plan Your Trade & Trade Your Plan" swing-trading rules, shows zones on a chart, and backtests the rules.

## User

- Retail trader in India learning demand/supply zone trading; not a professional developer.
- Writes short, informal messages, often with typos ("plz", "hogin" = hover). Infer intent; ask only if truly ambiguous.
- Wants plain-language explanations with concrete numbers from their own screen (e.g. the KOTAKBANK row).
- Windows 11, VS Code, PowerShell. Starts the app with `start.bat`.
- Not financial advice: when explaining trades, describe what the rules say and mention data/strategy limits.

## Run / test

```powershell
.\start.bat                                            # creates .venv on first run, starts server, opens browser
.venv\Scripts\python -m uvicorn app.main:app --reload  # manual start, http://127.0.0.1:8000
.venv\Scripts\python -m pytest tests                   # 23 tests
.venv\Scripts\python -m app.backtest KOTAKBANK INFY --min-grade B --aligned --cost 0.2   # CLI backtest
```

- No git repo. No `httpx2`, so FastAPI `TestClient` does not work: to test endpoints, start uvicorn on a spare
  port (e.g. 8765) in the background, curl it, then stop it.
- Check JS with `node --check static/app.js static/backtest.js` (no browser automation available).

## Layout

| Path | Role |
|---|---|
| `app/config.py` | All settings from `.env` (capital, risk %, R:R, ATR period, trend lookback, history lengths, cache TTLs) |
| `app/providers/` | `dhan.py` (Dhan HQ v2 REST) and `yahoo.py` (yfinance, `SYMBOL.NS`). Selected by `DATA_PROVIDER` |
| `app/data.py` | Loads + caches candles in `cache/{provider}_{SYMBOL}_{daily|60m|60m_long}.csv`; resamples W (from daily) and 2h (from 60m, bins at 09:15/11:15/13:15/15:15); reads `watchlist.txt` |
| `app/engine/indicators.py` | TR, ATR (RMA), boring/exciting candles (body ≤ 50% of range = boring), EMA 20/50 |
| `app/engine/zones.py` | Zone detection (DBR/RBR demand, RBD/DBD supply), proximal/distal, score /14 → grade A–D, freshness/tests/broken, nearest zones, HTF curve position |
| `app/engine/pulse_trend.py` | Pulse (EMA20 vs EMA50), Trend (7th-candle clock on EMA20, ±15° = sideways), `ACTION_MATRIX` |
| `app/engine/risk.py` | Trade plan: entry = proximal, SL = distal, target = 1:R:R, qty = capital×risk% ÷ risk/share |
| `app/scanner.py` | `analyze()` = full plan for one stock (HTF weekly → ITF daily → LTF 2h/1h); `chart_payload()`; `AGAINST_HTF` |
| `app/backtest.py` | Walk-forward backtest (see below) + CLI + `summarize()` |
| `app/journal.py` | Weekly forward test: saves last completed week's 2h zones (+ setup) with frozen lines into `journal.db` (SQLite), re-checks unfinished zones (touch + closing stop, broken, expired after `JOURNAL_EXPIRY_WEEKS`=8), split/bonus re-scaling via `ref_close`, `report()`, CSV export, CLI `python -m app.journal [--weeks N]`, background job `JOB` |
| `weekly.bat` | Runs the journal (for Windows Task Scheduler, Saturdays); appends to `journal.log` |
| `app/main.py` | API: `/api/settings`, `/api/analyze/{sym}`, `/api/chart/{sym}`, `/api/backtest/{sym}`, `/api/journal` (+ `/run` POST, `/status`, `/export`) |
| `static/journal.js` | Journal tab: run button + polling, status cards, results by group (closing vs touch stop), zone table with filters; symbol link opens the scanner chart |
| `static/app.js` | Scanner tab: scan worker pool (3 parallel), results table + pagination, detail cards, Lightweight Charts, tooltips (`TIPS`, `[data-tip]`), generic `renderPager(el, total, pg, rerender)` / `pageStart()` |
| `static/backtest.js` | Backtest tab: runs `/api/backtest` per stock, stats cards, equity curve, breakdown tables, per-stock + trades tables. Adds its own `TIPS` entries |
| `watchlist.txt` | 123 stocks from screener.in screen 3465658 "ravikumar" (fetched 2026-10-11). Old Nifty-50 list in `watchlist_nifty50.txt` |

## Strategy rules (as implemented)

- **Timeframes:** HTF = Weekly (zones + curve), ITF = Daily (pulse + trend → action), LTF = 2h or 1h (entry zone).
- **Action matrix:** positive+uptrend = "Buy / Long", positive+sideways = "Buy with conviction", negative+downtrend = "Sell / Short", negative+sideways = "Short with conviction", otherwise No action.
- **Curve:** range from nearest weekly DZ proximal to nearest weekly SZ proximal, split in 3. A BUY "In Supply Zone"/"High on curve" (or SELL in DZ/low) is flagged "against HTF".
- **Setup:** nearest LTF zone in the action's direction, only if tested ≤ 1 time.
- **Zone formation (user's rules, updated 2026-10-13, `find_zones`):** 1st candle TR ≥ ATR (any colour, no body rule);
  then 1–4 consecutive UOC candles = TR < ATR (any colour/body; `MAX_BASE_CANDLES=4`); then the 3rd candle
  (first candle after the group, so TR ≥ ATR) green = demand / red = supply, and it must GAP: open above the last
  UOC's body top (demand) / below its body bottom (supply); leg-out must also close beyond proximal.
  **Lines use only the UOC candles:** demand entry (proximal) = highest UOC high, SL (distal) = lowest UOC low − margin;
  supply mirrored. Margins = `ZONE_SL_MARGIN_ATR` and `ZONE_ENTRY_MARGIN_ATR` (both default 0.2) × ATR of the last UOC
  (demand entry = UOC high + entry margin; ONGC 3-Feb-2026 → 259.03 vs user's 258.95, first touch 16-Mar-2026 as the user said). Pattern name (DBR/RBR…) from leg-in colour.
  Chart: fresh demand green, fresh supply red, tested (price touched proximal again) gray, broken faded; chart and
  zones limited to the last 500 bars. Rules were settled with the user via AskUserQuestion; their notes contained
  contradictions (flowchart vs text), so ask before changing any rule.
- **1-2-4 rule (user, 2026-10-18):** heights = high − low; tallest UOC candle = 1, leg-in should be ≥ 2× and leg-out ≥ 4×
  (`ZONE_LEGIN_RATIO`, `ZONE_LEGOUT_RATIO`). **Not a filter** (user: "do not be strict"); it is the "best category":
  only zones meeting both can be grade A. Stored as `legin_filled`/`legout_filled` + ratios `legin_x`/`legout_x`.
  User's own ONGC (2.8×/2.4×) and OIL (1.1×/1.9×) zones do not meet it; their last UOC is tiny, the tallest is not.
- **Score /14:** UOC count (1=3, 2=2, 3–4=1) + base 1 + leg-in ≥ 2× 2 + leg-out ≥ 4× 4 + fresh 2/tested-once 1 + gap 1 +
  leg-out body > wick 1. Grade A = score ≥ 11 AND 1-2-4 met; B ≥ 8 (or ≥ 11 without 1-2-4); C ≥ 5; else D.

## Backtest design (keep these invariants)

- No lookahead: daily action from the last daily candle **before** the bar's day; weekly zones usable a week after their leg-out week and broken status only from finished weeks; LTF zone tests/breaks and grade (fresh points) counted only up to the current bar. `tests/test_backtest.py::test_no_lookahead` checks this (truncated vs full data give identical earlier trades).
- `daily_actions()` is a vectorised copy of `pulse()`/`trend()`/`action()` and must stay in sync with them (tested).
- Execution: limit at proximal, decision re-evaluated each bar close; gap through entry fills at open; order cancelled if the bar opens beyond the stop; SL wins when one bar touches both; one open trade per stock; one trade per zone; qty capped at capital ÷ price; costs = round-trip % of entry value, reported as `r_net`.
- Entry/stop are rounded to paise before computing the target.

## Findings so far (2026-10-11, Yahoo data, 123 stocks, 2h, 1:5, 0.2% costs, Nov 2023 – Oct 2026)

- 14.7k trades, win 16.5% (break-even 16.7%), avg −0.29R net (+0.04R gross), PF 0.74, equity curve a steady decline.
- Costs ≈ 0.23R per trade because zones are thin (median height 0.86% of price). Zones < 0.5% tall: −0.82R/trade. Zones > 2% tall: +0.06R/trade (only positive bucket).
- Grade A did **not** beat B/C. BUY better than SELL; fresh better than tested-once; "with HTF" helped only slightly.
- **Proposed next step (not built yet, waiting on user):** a "Min zone height %" filter in both scanner and backtest.

### Zone-accuracy study (2026-10-12)

Backtest trades now carry zone features (`height_pct`, `height_atr`, `legout_atr`, `boring`, `base_uoc`, `legin_filled`,
`legout_filled`, `gap`, `departure`, `age`, `dist_atr`, `room_ltf_r`, `room_htf_r`) and `run_symbol(..., stop_buffer_atr=)`
moves the SL beyond distal by N × LTF ATR (not exposed in the UI yet). Validation method: pick rules on H1
(fills before 2025-04-01), confirm on H2 (after). Scratch scripts were in the session scratchpad (`bt_run.py`, `analyze.py`).

- **Gross R ≈ 0 in almost every bucket.** Textbook quality signs (strong leg-out, gap, base UOC, 1 boring candle,
  big departure, fresh) do **not** predict better gross results consistently; several are slightly worse.
- Net differences come mostly from cost-in-R: thin zones (height < 0.5 ATR or < 0.5% of price) lose because costs are large vs the stop.
- Variants (all trades, net R/trade H1 / H2): base 1:5 −0.20 / −0.37; SL buffer 0.5 ATR −0.02 / −0.16;
  1:2 −0.27 / −0.37; 1:2 + buffer 0.5 −0.10 / −0.16; 1:3 + buffer 1.0 −0.00 / −0.12.
  BUY-only with height ≥ 1 ATR + buffer 0.5: +0.18 / −0.09. **No configuration was positive in both halves.**
- Conclusion so far: a stop buffer clearly reduces losses, but the mechanical zone rules show no stable edge.

### User's own zone sheet (8 trades, 1–2 Mar 2025, all 1:5)

JSWSTEEL D 888/882, TITAN D 3013/3003, TATAELXSI D 4637/4601, SBIN 15-min S 690.1/691.65, M&M D 2595/2561,
OIL D 337/329, GAIL D 115.52/114.47, NESTLEIND D 2121/2100 (Yahoo data is bonus-adjusted: divide by 2).
Green rows ≈ target hit. **User: test zones on the 2h timeframe only** (SBIN row is 15 min).
- NESTLEIND 2121/2100 (2h): base candle 27-Apr-2023 (daily RBR 2114.7/2100 matches all rules), older than Yahoo's
  hourly history (starts 31-Oct-2023), so the 2h zone cannot be detected with Yahoo data. Trade replay on 2h:
  filled 04-Mar-2025 (low 2118), SL never touched, target 2226 hit 07-Mar-2025 (high 2238.5).
- With a wick (touch) stop almost all were stopped first, but TITAN, M&M, OIL, SBIN hit the target afterwards.
- With a **closing-basis stop** on 1h candles 5 of 6 filled trades hit the target, which matches the sheet. The user's
  method probably uses a closing-basis SL. `run_symbol(..., close_stop=True)` implements it (exit at the close beyond SL).
- `find_zones` matched JSW (1h DBR), M&M (2h RBR), GAIL (daily DBR), roughly SBIN; it did not find TITAN, TATAELXSI, OIL zones.
- Caveat: early March 2025 was the Nifty bottom before a strong rally, so buy zones then were favoured; 8 trades is a tiny sample.

Full backtest with closing-basis stop (123 stocks, net R/trade H1 / H2): 2h all −0.17 / −0.44; 2h BUY +0.03 / −0.36.
Win rate rises from ~16% to ~28% but the average loss doubles to ~−2R (closes land well beyond the SL).
Best subset 2h close-stop BUY with height ≥ 0.5 ATR: +0.15 / −0.13. Still no configuration positive in both halves;
every configuration is worse in H2 (Apr 2025 – Oct 2026).

## Gotchas

- **Data provider:** user's Dhan account is on the FREE plan, so the chart APIs return `DH-902 ... requires a PLUS subscription` (HTTP 401). Keep `DATA_PROVIDER=yahoo`. Dhan credentials are in `.env`. Never print the token.
- **Yahoo limits:** 60m history ≈ 2–3 years; recent listings (LENSKART, TMCV, TMPV, SWIGGY, ATHERENERG) have little weekly history ("No curve").
- **Stale server:** `--reload` sometimes fails to pick up new routes, and old uvicorn processes can keep holding port 8000 after their terminal is closed (a 404 on a new route means old code). Find it with `Get-NetTCPConnection -LocalPort 8000 -State Listen` and ask the user before killing anything.
- **CSS:** `[hidden] { display: none !important; }` is required because `main`, `#controls` and `.pager` set `display`.
- **Lightweight Charts 4.1.3** (unpkg) has no price-scale `setVisibleRange`. Vertical zoom/pan is custom: `autoscaleInfoProvider` on the candle series with `state.view.{zoom, shift}`; other series use `autoscaleInfoProvider: () => null`. Price-axis drag is disabled on purpose. Double-click resets.
- Chart times: naive IST timestamps are passed as if UTC (`t.timestamp()` / `Date.parse(iso + "Z")`) so the axis reads IST.
- `#chart` is reused across redraws, so listeners on it are bound once (`el.dataset.vzoom`) and read `state.chart` / `state.candles`.
- Indian cash market cannot hold short positions overnight; SELL setups need F&O. Mention this when relevant.

### After switching to the user's zone rules (2026-10-12)

- Every detected zone was verified against the rules on 5 stocks × 4 timeframes (0 violations).
- Zones from the user's sheet now found: NESTLEIND daily (exact stop), JSW/SBIN close; TITAN, TATAELXSI, OIL, M&M not found
  (probably drawn on another timeframe; user has not said which yet).
- Backtest 2h 1:5, 0.2% costs (net R/trade H1 / H2): wick stop −0.37 / −0.50 (about half as many trades as before);
  + 0.5 ATR buffer −0.08 / −0.24 (BUY only +0.00 / −0.14); closing-basis stop −0.31 / −0.62.
  Gross R still ≈ 0. The new rules make bases smaller (TR < ATR), so zones are thinner and costs weigh more.
- 2026-10-13: lines switched to UOC high / UOC low − 0.2 ATR and the 1st-candle body rule dropped (user's OIL 17-Jul-2026
  zone is now found: entry 436.70, SL 428.42). User's ONGC 3-Feb-2026 lines were 258.95 / 255.40 vs app 258.10 / 250.42
  (user's SL looks like last-UOC low 256.40 − 1; their entry is above the UOC high). Backtest not rerun yet with these lines.
- 2026-10-13 backtest with these rules (v3, 2h, 1:5, 0.2% costs, net R/trade H1 / H2, ~9.1k trades):
  wick stop all −0.06 / −0.21, BUY −0.00 / −0.14; closing-basis stop all +0.03 / −0.25, **BUY +0.17 / −0.10**
  (gross BUY +0.33 / +0.08). Best so far, but still negative in H2. Median zone 1.26% of price, cost ≈ 0.16R.
- 2026-10-18 backtest v4 (1-2-4 grading, 2h, 1:5, 0.2% costs, net R/trade H1 / H2): closing-basis stop, **BUY + 1-2-4 met:
  +0.16 / +0.015** (gross +0.38 / +0.27, win ~31%, ~650 trades per half) — first subset positive in both halves, but H2 is
  barely above zero. Closing stop BUY all: +0.18 / −0.10. Wick stop BUY + 1-2-4: −0.05 / −0.15.
  1-2-4 zones are ~22% of all zones. Cache writes are now atomic (parallel runs once produced empty CSVs).
- 2026-10-25: weekly journal built (user chose: all new zones + setups, button + scheduler, 8-week expiry). First run
  saved 4 weeks (28-Sep … 19-Oct-2026, 709 zones; first 3 weeks marked backfilled). Backfilled results so far negative
  (setups closing stop −0.13R/trade on 93 trades). Snapshot uses only candles before the week's Saturday 00:00
  (tested by `test_snapshot_uses_no_future_data`); checking starts the following Monday.
