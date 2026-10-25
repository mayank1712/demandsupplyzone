# Demand & Supply Zone Scanner

A web dashboard that scans NSE stocks with the **Plan Your Trade & Trade Your Plan** rules
(swing trader: HTF Weekly, ITF Daily, LTF 2h / 1h) and shows the zones on a chart.

## Setup (Windows)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then put your Dhan client id + access token in .env
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and press **Scan watchlist**.

- The Dhan access token expires every 24 hours. Generate a new one on web.dhan.co each day.
- To try the scanner without a token, set `DATA_PROVIDER=yahoo` in `.env`.
- Edit `watchlist.txt` to choose the stocks.
- Run the tests with `.venv\Scripts\python -m pytest tests`.

## Backtest

Open the **Backtest** tab (or run `.venv\Scripts\python -m app.backtest KOTAKBANK INFY --min-grade B --aligned --cost 0.2`).
It replays ~3 years of candles bar by bar with the same rules as the scanner, using only data known at each moment
(daily action from yesterday's close, finished weekly candles, LTF zone tests counted up to the current bar).
Limit order at the proximal line, SL at distal, target 1:R:R; one open trade per stock and one trade per zone;
a candle touching both SL and target counts as a loss. Results are in R (1R = amount risked). Code: `app/backtest.py`.

## Weekly journal (forward test)

Open the **Journal** tab and press **Save & check now**, or run `weekly.bat`. Each run saves the 2h zones formed in the
last completed week (plus the trade setup at Friday's close) with frozen entry / SL / 1:5 target into `journal.db`,
then checks every earlier zone: waiting → filled → target / stop (touch stop and closing-basis stop), broken, or
expired after 8 weeks. Export to Excel with the CSV link. Code: `app/journal.py`.

Run it automatically every Saturday at 10:00 (PowerShell, once):

```powershell
schtasks /Create /TN "ZoneJournal" /SC WEEKLY /D SAT /ST 10:00 /TR "\"$PWD\weekly.bat\""
```

Remove it with `schtasks /Delete /TN "ZoneJournal" /F`. Output goes to `journal.log`.

## What it does

| Step | Rule | Code |
|---|---|---|
| Candle | Boring: body ≤ 50% of range. Exciting: body > 50% | `app/engine/indicators.py` |
| Zone | 1st candle TR ≥ ATR → 1–4 UOC candles (TR < ATR) → 3rd candle TR ≥ ATR that gaps away (green = Demand DBR/RBR, red = Supply RBD/DBD). Entry = UOC high (demand) / low (supply). SL = UOC low − 0.2 ATR (demand) / UOC high + 0.2 ATR (supply), set by `ZONE_SL_MARGIN_ATR`. Fresh = green/red, tested = gray | `app/engine/zones.py` |
| Validation | Boring count (1 Great, 2 Good, 3-4 So-so, >4 Garbage), TR vs ATR 1-2-4 (base UOC, leg-in Filled, leg-out Filled), fresh vs tested, leg-out gap, leg-out body > wick → score /14, grade A–D | `app/engine/zones.py` |
| Pulse | Daily EMA 20 vs 50 crossover | `app/engine/pulse_trend.py` |
| Trend | 7th candle clock rule on EMA 20 (12-3 up, ~3 sideways, 3-6 down) | `app/engine/pulse_trend.py` |
| Action | Pulse + Trend matrix (Buy, Buy with conviction, No action, Sell…) | `app/engine/pulse_trend.py` |
| Curve | Nearest weekly DZ → SZ split into 3 parts (low / equilibrium / high) | `app/engine/zones.py` |
| Risk | Entry = proximal, SL = distal, target 1:5, qty = (capital × risk%) ÷ (entry − SL) | `app/engine/risk.py` |

Settings such as the max number of boring candles, the ATR period and the trend angle can be changed in `.env` (see `app/config.py`).
